locals {
  requests_metric = "url_shortener.http.server.requests"
  errors_metric   = "url_shortener.http.server.errors"
  duration_metric = "url_shortener.http.server.request.duration"

  workbook_queries = [
    {
      title = "A. Request rate over time (requests / 5 minutes)"
      query = <<-KQL
        customMetrics
        | where name == "${local.requests_metric}"
        | summarize Requests = sum(valueSum) by bin(timestamp, 5m), cloud_RoleName
        | order by timestamp asc
      KQL
    },
    {
      title = "B. Server errors over time (errors / 5 minutes)"
      query = <<-KQL
        customMetrics
        | where name == "${local.errors_metric}"
        | summarize Errors = sum(valueSum) by bin(timestamp, 5m), cloud_RoleName
        | order by timestamp asc
      KQL
    },
    {
      title = "C. Request latency (average and maximum seconds)"
      query = <<-KQL
        customMetrics
        | where name == "${local.duration_metric}"
        | summarize AverageSeconds = sum(valueSum) / sum(valueCount), MaxSeconds = max(valueMax) by bin(timestamp, 5m), cloud_RoleName
        | order by timestamp asc
      KQL
    },
    {
      title = "D. Requests and server errors by service"
      query = <<-KQL
        customMetrics
        | where name in ("${local.requests_metric}", "${local.errors_metric}")
        | summarize Total = sum(valueSum) by cloud_RoleName, name
        | order by cloud_RoleName asc, name asc
      KQL
    },
    {
      title = "E. Recent 5xx requests and dependencies"
      query = <<-KQL
        union isfuzzy=true requests, dependencies
        | where toint(resultCode) >= 500
        | project timestamp, itemType, cloud_RoleName, name, resultCode, operation_Id
        | order by timestamp desc
        | take 50
      KQL
    },
    {
      title = "F. Correlation / trace investigation"
      query = <<-KQL
        union isfuzzy=true requests, dependencies
        | project timestamp, itemType, cloud_RoleName, name, operation_Id, id, operation_ParentId, resultCode
        | order by timestamp desc
        | take 100
      KQL
    },
  ]
}

resource "azurerm_log_analytics_workspace" "observability" {
  name                       = "log-ous-${random_string.suffix.result}"
  location                   = azurerm_resource_group.assessment.location
  resource_group_name        = azurerm_resource_group.assessment.name
  sku                        = "PerGB2018"
  retention_in_days          = 30
  daily_quota_gb             = 1
  internet_ingestion_enabled = true
  internet_query_enabled     = true
  tags                       = local.common_tags
}

resource "azurerm_application_insights" "observability" {
  name                         = "appi-ous-${random_string.suffix.result}"
  location                     = azurerm_resource_group.assessment.location
  resource_group_name          = azurerm_resource_group.assessment.name
  workspace_id                 = azurerm_log_analytics_workspace.observability.id
  application_type             = "web"
  daily_data_cap_in_gb         = 1
  sampling_percentage          = 100
  local_authentication_enabled = false
  ip_masking_enabled           = true
  internet_ingestion_enabled   = true
  internet_query_enabled       = true
  tags                         = local.common_tags
}

resource "azurerm_role_assignment" "shortener_telemetry" {
  scope                = azurerm_application_insights.observability.id
  role_definition_name = "Monitoring Metrics Publisher"
  principal_id         = azurerm_user_assigned_identity.shortener.principal_id
  principal_type       = "ServicePrincipal"
  description          = "Shortener managed identity may publish traces and metrics only."
}

resource "azurerm_role_assignment" "resolver_telemetry" {
  scope                = azurerm_application_insights.observability.id
  role_definition_name = "Monitoring Metrics Publisher"
  principal_id         = azurerm_user_assigned_identity.resolver.principal_id
  principal_type       = "ServicePrincipal"
  description          = "Resolver managed identity may publish traces and metrics only."
}

resource "azurerm_application_insights_workbook" "production" {
  name                = uuidv5("dns", "observable-url-shortener-${random_string.suffix.result}")
  resource_group_name = azurerm_resource_group.assessment.name
  location            = azurerm_resource_group.assessment.location
  display_name        = "Observable URL Shortener - Production Observability"
  description         = "RED metrics, failures, and trace investigation for both services."
  category            = "workbook"
  source_id           = lower(azurerm_application_insights.observability.id)
  tags                = local.common_tags

  data_json = jsonencode({
    version = "Notebook/1.0"
    items = concat(
      [
        {
          type = 1
          name = "operational-workflow"
          content = {
            json = "# Production observability\nUse RED panels to identify a service/operation, inspect a representative distributed trace, then use its trace and correlation IDs to locate structured Container Apps logs. Duration is shown as exported histogram average/max because Application Insights does not currently expose a defensible p95 for this custom histogram representation."
          }
        }
      ],
      [
        for index, panel in local.workbook_queries : {
          type = 3
          name = "panel-${index + 1}"
          content = {
            version      = "KqlItem/1.0"
            title        = panel.title
            query        = trimspace(panel.query)
            size         = 0
            queryType    = 0
            resourceType = "microsoft.insights/components"
            timeContext = {
              durationMs = 3600000
            }
          }
        }
      ]
    )
    fallbackResourceIds = [lower(azurerm_application_insights.observability.id)]
  })
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "server_errors" {
  name                 = "alert-ous-server-errors-${random_string.suffix.result}"
  resource_group_name  = azurerm_resource_group.assessment.name
  location             = azurerm_resource_group.assessment.location
  display_name         = "Observable URL Shortener - server errors detected"
  description          = "Raises when explicit application HTTP >=500 error metrics exceed zero. HTTP 404 is excluded by instrument semantics."
  severity             = 2
  enabled              = true
  evaluation_frequency = "PT5M"
  window_duration      = "PT5M"
  scopes               = [azurerm_application_insights.observability.id]
  tags                 = local.common_tags

  criteria {
    query                   = <<-KQL
      customMetrics
      | where name == "${local.errors_metric}"
      | summarize TotalErrors = sum(valueSum)
    KQL
    metric_measure_column   = "TotalErrors"
    operator                = "GreaterThan"
    threshold               = 0
    time_aggregation_method = "Total"

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  auto_mitigation_enabled = true
  skip_query_validation   = false
}
