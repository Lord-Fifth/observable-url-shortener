resource "azurerm_cosmosdb_account" "application" {
  name                = "cosmosous${random_string.suffix.result}"
  location            = azurerm_resource_group.assessment.location
  resource_group_name = azurerm_resource_group.assessment.name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  free_tier_enabled                = true
  local_authentication_enabled     = false
  public_network_access_enabled    = true
  automatic_failover_enabled       = false
  multiple_write_locations_enabled = false
  analytical_storage_enabled       = false
  burst_capacity_enabled           = false

  capacity {
    total_throughput_limit = 1000
  }

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = azurerm_resource_group.assessment.location
    failover_priority = 0
  }

  tags = local.common_tags
}

resource "azurerm_cosmosdb_sql_database" "application" {
  name                = local.database_name
  resource_group_name = azurerm_resource_group.assessment.name
  account_name        = azurerm_cosmosdb_account.application.name
  throughput          = 1000
}

resource "azurerm_cosmosdb_sql_container" "url_mappings" {
  name                  = local.mappings_name
  resource_group_name   = azurerm_resource_group.assessment.name
  account_name          = azurerm_cosmosdb_account.application.name
  database_name         = azurerm_cosmosdb_sql_database.application.name
  partition_key_paths   = ["/code"]
  partition_key_version = 2
}

resource "azurerm_cosmosdb_sql_container" "redirect_events" {
  name                  = local.events_name
  resource_group_name   = azurerm_resource_group.assessment.name
  account_name          = azurerm_cosmosdb_account.application.name
  database_name         = azurerm_cosmosdb_sql_database.application.name
  partition_key_paths   = ["/code"]
  partition_key_version = 2
}
