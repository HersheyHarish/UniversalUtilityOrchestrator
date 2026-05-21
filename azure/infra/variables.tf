variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "eastus2"
}

variable "environment" {
  description = "Deployment environment label"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "suffix" {
  description = "Short unique suffix appended to globally-scoped resource names"
  type        = string
  default     = "ua002"
  validation {
    condition     = length(var.suffix) <= 8 && can(regex("^[a-z0-9]+$", var.suffix))
    error_message = "suffix must be lowercase alphanumeric, max 8 characters."
  }
}

variable "model_format" {
  description = "Azure Foundry model format to deploy"
  type        = string
  default     = "OpenAI"
}

variable "model_name" {
  description = "Azure Foundry model name to deploy"
  type        = string
  default     = "gpt-4o"
}

variable "model_version" {
  description = "Azure Foundry model version to deploy"
  type        = string
  default     = ""
}

variable "model_capacity_tpm" {
  description = "Tokens per minute capacity in thousands (e.g. 30 = 30K TPM)"
  type        = number
  default     = 30
}

variable "cosmos_database_name" {
  description = "Cosmos DB SQL database name"
  type        = string
  default     = "utility_agent_db"
}

variable "function_app_python_version" {
  description = "Python runtime version for the Function App"
  type        = string
  default     = "3.11"
}

variable "tags" {
  description = "Additional tags merged onto all resources"
  type        = map(string)
  default     = {}
}

variable "registry_session_ttl_hours" {
  description = "Admin UI session lifetime in hours (stored in Cosmos TTL)"
  type        = number
  default     = 8
}

variable "swa_location" {
  description = "Azure region for the registry Static Web App "
  type    = string
  default = "eastus2"
}