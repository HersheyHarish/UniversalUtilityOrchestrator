variable "resource_group_name" { type = string }
variable "location"            { type = string }
variable "function_app_name"   { type = string }
variable "storage_name"        { type = string }
variable "python_version"      { type = string }
variable "app_settings"        { type = map(string) }
variable "tags"                { type = map(string) }
variable "cors_allowed_origins" {
  description = "List of allowed CORS origins (e.g. SWA URL). Empty list disables custom CORS."
  type        = list(string)
  default     = ["*"]
}

resource "azurerm_storage_account" "this" {
  name                     = var.storage_name
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"

  allow_nested_items_to_be_public = false

  tags = var.tags
}

resource "azurerm_service_plan" "this" {
  name                = "asp-${var.function_app_name}"
  location            = var.location
  resource_group_name = var.resource_group_name
  os_type             = "Linux"
  sku_name            = "Y1"
  tags                = var.tags
}

resource "azurerm_linux_function_app" "this" {
  name                       = var.function_app_name
  location                   = var.location
  resource_group_name        = var.resource_group_name
  service_plan_id            = azurerm_service_plan.this.id
  storage_account_name       = azurerm_storage_account.this.name
  storage_account_access_key = azurerm_storage_account.this.primary_access_key

  identity {
    type = "SystemAssigned"
  }

  site_config {
    application_stack {
      python_version = var.python_version
    }

    health_check_path = "/api/health"
    health_check_eviction_time_in_min = 10

    cors {
      allowed_origins     = var.cors_allowed_origins
      support_credentials = false
    }
  }

  app_settings = merge(var.app_settings, {
    FUNCTIONS_WORKER_RUNTIME  = "python"
    FUNCTIONS_EXTENSION_VERSION = "~4"
    WEBSITE_RUN_FROM_PACKAGE  = "1"
  })

  lifecycle {
    ignore_changes = [
      app_settings["WEBSITE_RUN_FROM_PACKAGE"],
    ]
  }

  tags = var.tags
}

output "function_app_id"   { value = azurerm_linux_function_app.this.id }
output "function_app_name" { value = azurerm_linux_function_app.this.name }
output "default_hostname"  { value = azurerm_linux_function_app.this.default_hostname }
output "principal_id"      { value = azurerm_linux_function_app.this.identity[0].principal_id }
