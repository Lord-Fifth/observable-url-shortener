resource "azurerm_user_assigned_identity" "shortener" {
  name                = "id-ous-shortener-${random_string.suffix.result}"
  location            = azurerm_resource_group.assessment.location
  resource_group_name = azurerm_resource_group.assessment.name
  tags                = local.common_tags
}

resource "azurerm_user_assigned_identity" "resolver" {
  name                = "id-ous-resolver-${random_string.suffix.result}"
  location            = azurerm_resource_group.assessment.location
  resource_group_name = azurerm_resource_group.assessment.name
  tags                = local.common_tags
}

