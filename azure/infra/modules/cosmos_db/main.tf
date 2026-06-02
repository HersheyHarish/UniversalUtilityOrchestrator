variable "resource_group_name" { type = string }
variable "location"            { type = string }
variable "account_name"        { type = string }
variable "database_name"       { type = string }
variable "tags"                { type = map(string) }

resource "azurerm_cosmosdb_account" "this" {
  name                = var.account_name
  location            = var.location
  resource_group_name = var.resource_group_name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  capabilities {
    name = "EnableServerless"
  }

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = var.location
    failover_priority = 0
  }

  identity {
    type = "SystemAssigned"
  }

  ip_range_filter               = ["0.0.0.0"]
  public_network_access_enabled = true

  tags = var.tags
}

resource "azurerm_cosmosdb_sql_database" "this" {
  name                = var.database_name
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.this.name
}

locals {
  containers = {
    admin_sessions = {
      default_ttl = null
    }
    agents = {
      default_ttl = null
    }
    messages = {
      default_ttl = null
    }
    sessions = {
      default_ttl = null
    }
    traces = {
      default_ttl = null
    }
  }
}

resource "azurerm_cosmosdb_sql_container" "containers" {
  for_each = local.containers

  name                = each.key
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.this.name
  database_name       = azurerm_cosmosdb_sql_database.this.name
  partition_key_paths  = ["/partition_key"]
  default_ttl         = each.value.default_ttl

  indexing_policy {
    indexing_mode = "consistent"
    included_path { path = "/*" }
    excluded_path { path = "/\"_etag\"/?" }
  }
}

output "account_id"    { value = azurerm_cosmosdb_account.this.id }
output "account_name"  { value = azurerm_cosmosdb_account.this.name }
output "endpoint"      { value = azurerm_cosmosdb_account.this.endpoint }
output "database_name" { value = azurerm_cosmosdb_sql_database.this.name }
