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

output "log_analytics_workspace_name" {
  description = "Log Analytics workspace receiving Container Apps stdout/stderr."
  value       = azurerm_log_analytics_workspace.observability.name
}

output "log_analytics_workspace_id" {
  description = "Log Analytics customer/workspace identifier for Azure CLI queries."
  value       = azurerm_log_analytics_workspace.observability.workspace_id
}

output "application_insights_name" {
  description = "Shared workspace-based Application Insights component."
  value       = azurerm_application_insights.observability.name
}

output "application_insights_app_id" {
  description = "Application Insights application identifier for Azure CLI queries."
  value       = azurerm_application_insights.observability.app_id
}

output "observability_workbook_id" {
  description = "Terraform-managed production observability workbook resource ID."
  value       = azurerm_application_insights_workbook.production.id
}

output "server_error_alert_id" {
  description = "Terraform-managed scheduled query alert resource ID."
  value       = azurerm_monitor_scheduled_query_rules_alert_v2.server_errors.id
}
