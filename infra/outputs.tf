output "resource_group_name" {
  description = "Terraform-owned assessment resource group."
  value       = azurerm_resource_group.assessment.name
}

output "cosmos_account_name" {
  description = "Cosmos DB for NoSQL account name."
  value       = azurerm_cosmosdb_account.application.name
}

output "shortener_app_name" {
  description = "Shortener Container App name used for internal service discovery."
  value       = azurerm_container_app.shortener.name
}

output "resolver_app_name" {
  description = "Resolver Container App name."
  value       = azurerm_container_app.resolver.name
}

output "shortener_url" {
  description = "Public shortener HTTPS origin."
  value       = "https://${azurerm_container_app.shortener.ingress[0].fqdn}"
}

output "resolver_url" {
  description = "Public resolver HTTPS origin."
  value       = "https://${azurerm_container_app.resolver.ingress[0].fqdn}"
}

