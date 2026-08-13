resource "azurerm_container_app_environment" "application" {
  name                = "cae-ous-${random_string.suffix.result}"
  location            = azurerm_resource_group.assessment.location
  resource_group_name = azurerm_resource_group.assessment.name
  tags                = local.common_tags

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
    minimum_count         = 0
    maximum_count         = 0
  }
}

resource "azurerm_container_app" "resolver" {
  name                         = "ous-resolver-${random_string.suffix.result}"
  container_app_environment_id = azurerm_container_app_environment.application.id
  resource_group_name          = azurerm_resource_group.assessment.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = local.common_tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.resolver.id]
  }

  ingress {
    external_enabled           = true
    allow_insecure_connections = false
    target_port                = 8080
    transport                  = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 2

    container {
      name   = "resolver"
      image  = local.resolver_image
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "SHORTENER_BASE_URL"
        value = "http://ous-shortener-${random_string.suffix.result}"
      }
      env {
        name  = "SHORTENER_TIMEOUT_SECONDS"
        value = "2.0"
      }
      env {
        name  = "REPOSITORY_BACKEND"
        value = "cosmos"
      }
      env {
        name  = "COSMOS_ENDPOINT"
        value = azurerm_cosmosdb_account.application.endpoint
      }
      env {
        name  = "COSMOS_DATABASE_NAME"
        value = azurerm_cosmosdb_sql_database.application.name
      }
      env {
        name  = "COSMOS_REDIRECT_EVENTS_CONTAINER"
        value = azurerm_cosmosdb_sql_container.redirect_events.name
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.resolver.client_id
      }
      env {
        name  = "OTEL_SERVICE_NAME"
        value = "resolver"
      }

      liveness_probe {
        transport               = "HTTP"
        port                    = 8080
        path                    = "/healthz"
        initial_delay           = 3
        interval_seconds        = 10
        timeout                 = 2
        failure_count_threshold = 3
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = 8080
        path                    = "/readyz"
        initial_delay           = 3
        interval_seconds        = 5
        timeout                 = 2
        failure_count_threshold = 3
        success_count_threshold = 1
      }
    }
  }

  depends_on = [azurerm_cosmosdb_sql_role_assignment.resolver_events]
}

resource "azurerm_container_app" "shortener" {
  name                         = "ous-shortener-${random_string.suffix.result}"
  container_app_environment_id = azurerm_container_app_environment.application.id
  resource_group_name          = azurerm_resource_group.assessment.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = local.common_tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.shortener.id]
  }

  ingress {
    external_enabled           = true
    allow_insecure_connections = false
    target_port                = 8080
    transport                  = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 2

    container {
      name   = "shortener"
      image  = local.shortener_image
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "RESOLVER_BASE_URL"
        value = "https://${azurerm_container_app.resolver.ingress[0].fqdn}"
      }
      env {
        name  = "SHORT_CODE_LENGTH"
        value = "8"
      }
      env {
        name  = "SHORT_CODE_MAX_ATTEMPTS"
        value = "5"
      }
      env {
        name  = "REPOSITORY_BACKEND"
        value = "cosmos"
      }
      env {
        name  = "COSMOS_ENDPOINT"
        value = azurerm_cosmosdb_account.application.endpoint
      }
      env {
        name  = "COSMOS_DATABASE_NAME"
        value = azurerm_cosmosdb_sql_database.application.name
      }
      env {
        name  = "COSMOS_MAPPINGS_CONTAINER"
        value = azurerm_cosmosdb_sql_container.url_mappings.name
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.shortener.client_id
      }
      env {
        name  = "OTEL_SERVICE_NAME"
        value = "shortener"
      }

      liveness_probe {
        transport               = "HTTP"
        port                    = 8080
        path                    = "/healthz"
        initial_delay           = 3
        interval_seconds        = 10
        timeout                 = 2
        failure_count_threshold = 3
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = 8080
        path                    = "/readyz"
        initial_delay           = 3
        interval_seconds        = 5
        timeout                 = 2
        failure_count_threshold = 3
        success_count_threshold = 1
      }
    }
  }

  depends_on = [azurerm_cosmosdb_sql_role_assignment.shortener_mappings]
}
