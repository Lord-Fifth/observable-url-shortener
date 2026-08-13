locals {
  cosmos_data_contributor_role_id = "${azurerm_cosmosdb_account.application.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  mappings_scope                  = "${azurerm_cosmosdb_account.application.id}/dbs/${azurerm_cosmosdb_sql_database.application.name}/colls/${azurerm_cosmosdb_sql_container.url_mappings.name}"
  events_scope                    = "${azurerm_cosmosdb_account.application.id}/dbs/${azurerm_cosmosdb_sql_database.application.name}/colls/${azurerm_cosmosdb_sql_container.redirect_events.name}"
}

resource "azurerm_cosmosdb_sql_role_assignment" "shortener_mappings" {
  resource_group_name = azurerm_resource_group.assessment.name
  account_name        = azurerm_cosmosdb_account.application.name
  role_definition_id  = local.cosmos_data_contributor_role_id
  principal_id        = azurerm_user_assigned_identity.shortener.principal_id
  scope               = local.mappings_scope
}

resource "azurerm_cosmosdb_sql_role_assignment" "resolver_events" {
  resource_group_name = azurerm_resource_group.assessment.name
  account_name        = azurerm_cosmosdb_account.application.name
  role_definition_id  = local.cosmos_data_contributor_role_id
  principal_id        = azurerm_user_assigned_identity.resolver.principal_id
  scope               = local.events_scope
}

