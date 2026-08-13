# Azure infrastructure

This Terraform root creates the complete Phase 5 application infrastructure in Australia East:
one resource group, one Consumption Container Apps environment, two independently identified
Container Apps, one free-tier Cosmos DB for NoSQL account, and one Azure-native observability
stack. The Cosmos database has 1000 RU/s shared provisioned throughput and two containers with no
dedicated throughput.

The observability stack is one 30-day `PerGB2018` Log Analytics workspace, one workspace-based
Application Insights component capped at 1 GB/day, two Application Insights-scoped
`Monitoring Metrics Publisher` assignments, one six-query workbook, and one enabled server-error
scheduled query alert. Linking the existing Container Apps Environment to the workspace is an
in-place update. Application Insights local authentication is disabled; its connection string is
resource-routing configuration and both applications authenticate export with their own existing
user-assigned identity.

Authentication uses the active Azure CLI session for Terraform and separate user-assigned managed
identities for application data and telemetry access. Each Cosmos data-plane role assignment is
scoped to its owning container; telemetry publication is scoped only to Application Insights. No
Cosmos keys, client secrets, registry credentials, telemetry API keys, or other secrets are
Terraform inputs.

Local state is an intentional time-boxed assessment trade-off and is ignored by Git. The provider
lock file is committed. Use the repository-level `scripts/deploy-azure.ps1` orchestrator rather
than running an incomplete apply with image tags that have not been published.
