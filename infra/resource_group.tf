resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

resource "azurerm_resource_group" "assessment" {
  name     = "rg-observable-url-ase-${random_string.suffix.result}"
  location = var.location
  tags     = local.common_tags
}

