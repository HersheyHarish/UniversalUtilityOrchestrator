variable "resource_group_name" { type = string }
variable "location"            { type = string }
variable "account_name"        { type = string }
variable "deployment_name"     { type = string }
variable "model_name"          { type = string }
variable "model_format"        { type = string }
variable "model_version"       { type = string }
variable "model_capacity_tpm"  { type = number }
variable "tags"                { type = map(string) }

resource "azurerm_cognitive_account" "ai_foundry" {
  name                = var.account_name
  location            = var.location
  resource_group_name = var.resource_group_name
  kind                = "AIServices"
  sku_name            = "S0"
  custom_subdomain_name      = var.account_name
  project_management_enabled = true

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

resource "azurerm_cognitive_account_project" "agent_project" {
  name                  = "uuo-ai-project"
  location              = var.location
  cognitive_account_id  = azurerm_cognitive_account.ai_foundry.id

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_cognitive_deployment" "model" {
  name                 = var.deployment_name
  cognitive_account_id = azurerm_cognitive_account.ai_foundry.id

  model {
    format  = var.model_format 
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = "GlobalStandard"
    capacity = var.model_capacity_tpm   # TPM in thousands
  }
}

output "account_id"   { value = azurerm_cognitive_account.ai_foundry.id }
output "endpoint"   { value = "${azurerm_cognitive_account_project.agent_project.endpoints["AI Foundry API"]}/openai/v1" }
output "primary_key"  {
  value     = azurerm_cognitive_account.ai_foundry.primary_access_key
  sensitive = true
}
