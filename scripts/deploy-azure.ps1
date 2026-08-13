[CmdletBinding()]
param(
    [ValidateSet("australiaeast")]
    [string]$Location = "australiaeast",
    [string]$ImageTag,
    [switch]$SkipLocalValidation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$infraDirectory = Join-Path $repositoryRoot "infra"
$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"

function Invoke-Native {
    param(
        [Parameter(Mandatory)] [string]$Executable,
        [Parameter(ValueFromRemainingArguments)] [string[]]$Arguments
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable failed with exit code $LASTEXITCODE"
    }
}

function Get-NativeOutput {
    param(
        [Parameter(Mandatory)] [string]$Executable,
        [Parameter(ValueFromRemainingArguments)] [string[]]$Arguments
    )
    $output = & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable failed with exit code $LASTEXITCODE"
    }
    return ($output -join "`n").Trim()
}

function Test-GhcrCredential {
    $configPath = Join-Path $env:USERPROFILE ".docker\config.json"
    if (-not (Test-Path -LiteralPath $configPath)) {
        return $false
    }
    $config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
    $authsProperty = $config.PSObject.Properties["auths"]
    $authNames = @()
    if ($authsProperty) {
        $authNames = @($authsProperty.Value.PSObject.Properties | ForEach-Object { $_.Name })
    }
    if ($authNames | Where-Object { $_ -match "ghcr.io" }) {
        return $true
    }
    $storeProperty = $config.PSObject.Properties["credsStore"]
    if (-not $storeProperty -or -not $storeProperty.Value) {
        return $false
    }
    $helper = Get-Command "docker-credential-$($storeProperty.Value)" -ErrorAction SilentlyContinue
    if (-not $helper) {
        return $false
    }
    $rawEntries = "{}" | & $helper.Source list
    if ($LASTEXITCODE -ne 0) {
        return $false
    }
    $entries = ($rawEntries -join "`n") | ConvertFrom-Json
    $entryNames = @($entries.PSObject.Properties | ForEach-Object { $_.Name })
    return [bool]($entryNames | Where-Object { $_ -match "ghcr.io" })
}

function Test-PublicGhcrImage {
    param([Parameter(Mandatory)] [string]$Image)
    $withoutRegistry = $Image.Substring("ghcr.io/".Length)
    $separator = $withoutRegistry.LastIndexOf(":")
    $repository = $withoutRegistry.Substring(0, $separator)
    $tag = $withoutRegistry.Substring($separator + 1)
    try {
        $scope = [System.Uri]::EscapeDataString("repository:$repository`:pull")
        $tokenResponse = Invoke-RestMethod -Uri "https://ghcr.io/token?scope=$scope" -TimeoutSec 15
        if (-not $tokenResponse.token) {
            return $false
        }
        $headers = @{
            Authorization = "Bearer $($tokenResponse.token)"
            Accept        = "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json"
        }
        Invoke-WebRequest -UseBasicParsing -Method Head -Uri "https://ghcr.io/v2/$repository/manifests/$tag" -Headers $headers -TimeoutSec 15 | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

foreach ($command in @("az", "terraform", "docker", "git")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command is unavailable: $command"
    }
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Repository virtual environment is missing: run python -m venv .venv and install requirements-dev.txt"
}

$account = Get-NativeOutput az account show --output json | ConvertFrom-Json
if ($account.state -ne "Enabled") {
    throw "The selected Azure subscription is not Enabled."
}
$env:ARM_SUBSCRIPTION_ID = $account.id
Write-Host "Azure subscription: $($account.name) ($($account.id))"
Write-Host "Azure region: $Location"

Invoke-Native docker info --format "{{.ServerVersion}}"

if (-not $SkipLocalValidation) {
    Invoke-Native $python -m pytest -q -p no:cacheprovider
    Invoke-Native $python -m ruff check .
    Invoke-Native $python -m ruff format --check .
    Invoke-Native docker compose config --quiet
}

if (-not $ImageTag) {
    $files = Get-NativeOutput git ls-files --cached --others --exclude-standard
    $fingerprints = foreach ($file in ($files -split "`n" | Sort-Object)) {
        $hash = Get-NativeOutput git hash-object -- $file
        "$file`0$hash"
    }
    $fingerprintFile = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllLines($fingerprintFile, $fingerprints)
        $snapshotHash = Get-NativeOutput git hash-object $fingerprintFile
    }
    finally {
        Remove-Item -LiteralPath $fingerprintFile -Force
    }
    $ImageTag = "phase4-$($snapshotHash.Substring(0, 12))"
}
if ($ImageTag -notmatch "^[0-9a-z][0-9a-z._-]{6,127}$") {
    throw "ImageTag must be a lowercase immutable container tag."
}

$shortenerImage = "ghcr.io/lord-fifth/observable-url-shortener-shortener:$ImageTag"
$resolverImage = "ghcr.io/lord-fifth/observable-url-shortener-resolver:$ImageTag"
Write-Host "Immutable image tag: $ImageTag"

if (-not (Test-GhcrCredential)) {
    throw @"
No Docker credential for ghcr.io was found. Authenticate outside the repository, then rerun:
  `$env:CR_PAT | docker login ghcr.io -u lord-fifth --password-stdin
Use a GitHub token with write:packages; do not save the token in this repository.
"@
}

Invoke-Native docker build --tag $shortenerImage (Join-Path $repositoryRoot "services\shortener")
Invoke-Native docker build --tag $resolverImage (Join-Path $repositoryRoot "services\resolver")
Invoke-Native docker push $shortenerImage
Invoke-Native docker push $resolverImage
if (-not (Test-PublicGhcrImage $shortenerImage) -or -not (Test-PublicGhcrImage $resolverImage)) {
    throw "GHCR images were pushed but are not anonymously pullable. Set both package visibilities to Public in GitHub Packages, then rerun."
}

Invoke-Native terraform "-chdir=$infraDirectory" init
$planName = "phase4.tfplan"
Invoke-Native terraform "-chdir=$infraDirectory" plan -out=$planName "-var=image_tag=$ImageTag" "-var=location=$Location"
Invoke-Native $python (Join-Path $PSScriptRoot "validate-terraform-plan.py") (Join-Path $infraDirectory $planName) --infra-directory $infraDirectory
Invoke-Native terraform "-chdir=$infraDirectory" apply $planName

$outputs = Get-NativeOutput terraform "-chdir=$infraDirectory" output -json | ConvertFrom-Json
$shortenerUrl = $outputs.shortener_url.value
$resolverUrl = $outputs.resolver_url.value
Write-Host "Shortener URL: $shortenerUrl"
Write-Host "Resolver URL: $resolverUrl"

$smokeJson = Get-NativeOutput $python (Join-Path $PSScriptRoot "smoke-azure.py") --shortener-url $shortenerUrl --resolver-url $resolverUrl
$smoke = $smokeJson | ConvertFrom-Json
Write-Host "Live smoke passed for code $($smoke.code)"

$revision = Get-NativeOutput az containerapp revision list --resource-group $outputs.resource_group_name.value --name $outputs.shortener_app_name.value --query "[?properties.active].name | [0]" --output tsv
Invoke-Native az containerapp revision restart --resource-group $outputs.resource_group_name.value --name $outputs.shortener_app_name.value --revision $revision
Invoke-Native $python (Join-Path $PSScriptRoot "smoke-azure.py") --shortener-url $shortenerUrl --resolver-url $resolverUrl --existing-code $smoke.code --expected-target $smoke.target_url

Write-Host "Azure deployment and post-restart durability validation passed."
