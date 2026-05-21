variable "resource_group_name" { type = string }
variable "location"            { type = string }
variable "vault_name"          { type = string }
variable "tenant_id"           { type = string }
variable "admin_object_id"     { 
    type = string  
    description = "Object ID that gets Key Vault Administrator (deploying principal)"
  }
variable "openai_key"      { 
    type = string
    sensitive = true
  }
variable "tags"                { type = map(string) }

resource "azurerm_key_vault" "this" {
  name                      = var.vault_name
  location                  = var.location
  resource_group_name       = var.resource_group_name
  tenant_id                 = var.tenant_id
  sku_name                  = "standard"

  enable_rbac_authorization  = true
  soft_delete_retention_days = 7
  purge_protection_enabled   = true   # set to false for dev workload

  tags = var.tags
}

resource "azurerm_role_assignment" "admin" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = var.admin_object_id
}

resource "time_sleep" "rbac_propagation" {
  depends_on      = [azurerm_role_assignment.admin]
  create_duration = "30s"
}

resource "azurerm_key_vault_secret" "openai_key" {
  name         = "openai-key"
  value        = var.openai_key
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [time_sleep.rbac_propagation]
}

output "vault_id"   { value = azurerm_key_vault.this.id }
output "vault_name" { value = azurerm_key_vault.this.name }
output "vault_uri"  { value = azurerm_key_vault.this.vault_uri }
