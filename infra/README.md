# Azure infrastructure

This Terraform root creates the complete Phase 4 application infrastructure in Australia East:
one resource group, one Consumption Container Apps environment, two independently identified
Container Apps, and one free-tier Cosmos DB for NoSQL account. The Cosmos database has 1000 RU/s
shared provisioned throughput and two containers with no dedicated throughput.

Authentication uses the active Azure CLI session for Terraform and separate user-assigned managed
identities for application data access. Each Cosmos data-plane role assignment is scoped to its
owning container. No Cosmos keys, connection strings, client secrets, registry credentials, or
other secrets are Terraform inputs.

Local state is an intentional time-boxed assessment trade-off and is ignored by Git. The provider
lock file is committed. Use the repository-level `scripts/deploy-azure.ps1` orchestrator rather
than running an incomplete apply with image tags that have not been published.

