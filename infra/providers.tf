provider "azurerm" {
  resource_provider_registrations = "none"

  resource_providers_to_register = [
    "Microsoft.App",
    "Microsoft.DocumentDB",
    "Microsoft.OperationalInsights",
  ]

  features {}
}
