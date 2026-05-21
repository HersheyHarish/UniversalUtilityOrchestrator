terraform {
  required_version = ">= 1.7.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.73.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.11"
    }
  }

  # Uncomment to store state in Azure Blob (recommended for teams)
  # backend "azurerm" {
  #   resource_group_name  = "rg-tfstate"
  #   storage_account_name = "sttfstate-orchestrator"
  #   container_name       = "tfstate"
  #   key                  = "utility-agent.tfstate"
  # }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = false
      recover_soft_deleted_key_vaults = true
    }
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}

data "azurerm_client_config" "current" {}

locals {
  common_tags = merge(var.tags, {
    Environment = var.environment
    Project     = "UniversalUtilityAgent"
    ManagedBy   = "Terraform"
  })
}

module "resource_group" {
  source      = "./modules/resource_group"
  name        = "rg-utility-agent-${var.environment}"
  location    = var.location
  tags        = local.common_tags
}

module "cosmos_db" {
  source              = "./modules/cosmos_db"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  account_name        = "cosmos-${var.suffix}-${var.environment}"
  database_name       = var.cosmos_database_name
  tags                = local.common_tags
}

module "openai" {
  source               = "./modules/openai"
  resource_group_name  = module.resource_group.name
  location             = module.resource_group.location
  account_name         = "llm-ua-${var.suffix}"
  deployment_name      = var.model_name
  model_name           = var.model_name
  model_format         = var.model_format
  model_version        = var.model_version
  model_capacity_tpm   = var.model_capacity_tpm
  tags                 = local.common_tags
}

module "key_vault" {
  source              = "./modules/key_vault"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  vault_name          = "kv-ua-${var.suffix}"
  tenant_id           = data.azurerm_client_config.current.tenant_id
  admin_object_id     = data.azurerm_client_config.current.object_id
  openai_key          = module.openai.primary_key
  tags                = local.common_tags
}

module "orchestrator" {
  source              = "./modules/function_app"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  function_app_name   = "fn-orchestrator-${var.suffix}"
  storage_name        = "stua${var.suffix}"
  python_version      = var.function_app_python_version
  tags                = local.common_tags

  app_settings = {
    COSMOS_ENDPOINT             = module.cosmos_db.endpoint
    COSMOS_DATABASE             = var.cosmos_database_name
    AZURE_OPENAI_ENDPOINT       = module.openai.endpoint
    AZURE_OPENAI_DEPLOYMENT     = var.model_name
    KEY_VAULT_URL               = module.key_vault.vault_uri
    OPENAI_SECRET_NAME          = "openai-key"
    AGENT_TIMEOUT_SECS          = "45"
    AGENT_MAX_RETRIES           = "2"
  }
}

resource "azurerm_cosmosdb_sql_role_assignment" "orchestrator_cosmos" {
  resource_group_name = module.resource_group.name
  account_name        = module.cosmos_db.account_name
  # Built-in "Cosmos DB Built-in Data Contributor" role
  role_definition_id  = "${module.cosmos_db.account_id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = module.orchestrator.principal_id
  scope               = module.cosmos_db.account_id
}

resource "azurerm_role_assignment" "orchestrator_kv" {
  scope                = module.key_vault.vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = module.orchestrator.principal_id
}

resource "azurerm_role_assignment" "orchestrator_openai" {
  scope                = module.openai.account_id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = module.orchestrator.principal_id
}



module "registry" {
  source              = "./modules/function_app"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  function_app_name   = "fn-registry-${var.suffix}"
  storage_name        = "stuareg${var.suffix}"
  python_version      = var.function_app_python_version
  tags                = local.common_tags

  app_settings = {
    COSMOS_ENDPOINT    = module.cosmos_db.endpoint
    COSMOS_DATABASE    = var.cosmos_database_name
    KEY_VAULT_URL      = module.key_vault.vault_uri
    SESSION_TTL_HOURS  = tostring(var.registry_session_ttl_hours)
  }
}

module "swa" {
  source              = "./modules/static_web_app"
  name                = "swa-registry-${var.suffix}"
  resource_group_name = module.resource_group.name
  location            = var.swa_location
  tags                = local.common_tags
}

resource "azurerm_cosmosdb_sql_role_assignment" "registry_cosmos" {
  resource_group_name = module.resource_group.name
  account_name        = module.cosmos_db.account_name
  role_definition_id  = "${module.cosmos_db.account_id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = module.registry.principal_id
  scope               = module.cosmos_db.account_id
}

resource "azurerm_role_assignment" "registry_kv" {
  scope                = module.key_vault.vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = module.registry.principal_id
}

resource "azurerm_key_vault_secret" "registry_host_key" {
  name         = "registry-host-key"
  value        = "placeholder-set-by-deploy-sh"
  key_vault_id = module.key_vault.vault_id
  depends_on   = [module.key_vault]

  lifecycle { ignore_changes = [value] }
}

resource "azurerm_key_vault_secret" "swa_token" {
  name         = "swa-deployment-token"
  value        = module.swa.deployment_token
  key_vault_id = module.key_vault.vault_id
  depends_on   = [module.key_vault]
}
