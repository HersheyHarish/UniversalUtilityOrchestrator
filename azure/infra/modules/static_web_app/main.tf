

variable "name"                { type = string }
variable "resource_group_name" { type = string }
variable "location"            { type = string }
variable "tags"                { type = map(string) }

# Optional: domains that should be allowed as CORS origins on the registry
# function app. Populated by main.tf after SWA hostname is known.
# (Not used inside this module — exposed as output for use by main.tf.)

resource "azurerm_static_web_app" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku_tier            = "Free"
  sku_size            = "Free"
  tags                = var.tags
}

output "id"               { value = azurerm_static_web_app.this.id }
output "default_hostname" { value = azurerm_static_web_app.this.default_host_name }
output "url"              { value = "https://${azurerm_static_web_app.this.default_host_name}" }

output "deployment_token" {
  description = "API key used by swa deploy / deploy.sh to publish the React build"
  value       = azurerm_static_web_app.this.api_key
  sensitive   = true
}
