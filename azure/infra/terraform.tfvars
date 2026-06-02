# Copy this file to terraform.tfvars and edit before running deploy.sh
# Never commit terraform.tfvars — it is in .gitignore

location     = "eastus2"
environment  = "dev"
suffix       = "ua001"   # change if names collide globally

model_format  = "OpenAI"
model_name    = "gpt-5.4-mini"
model_version = "2026-03-17"
model_capacity_tpm  = 500

cosmos_database_name        = "utility_agent_db"
function_app_python_version = "3.11"

registry_session_ttl_hours = 8
swa_location = "eastus2"


tags = {
  Owner      = "Sanket"
  CostCenter = "capstone"
}
