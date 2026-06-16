variable "location" {
  type    = string
  default = "westeurope"
}

variable "project_name" {
  description = "Lowercase, alphanumeric only — used in storage account names"
  type        = string
  default     = "multicloudpipe"
}

variable "sql_admin_password" {
  description = "Set via terraform.tfvars (gitignored) or TF_VAR_sql_admin_password"
  type        = string
  sensitive   = true
}
