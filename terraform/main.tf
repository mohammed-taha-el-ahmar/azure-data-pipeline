resource "azurerm_resource_group" "main" {
  name     = "${var.project_name}-rg"
  location = var.location
}

# ---------------------------------------------------------------------------
# ADLS Gen2 — landing zone
# ---------------------------------------------------------------------------
resource "azurerm_storage_account" "datalake" {
  name                     = "${var.project_name}dl"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  is_hns_enabled           = true # enables ADLS Gen2 hierarchical namespace
}

resource "azurerm_storage_container" "raw" {
  name                  = "raw"
  storage_account_name  = azurerm_storage_account.datalake.name
  container_access_type = "private"
}

# ---------------------------------------------------------------------------
# Azure Data Factory — orchestration
# TODO: linked services, datasets, pipeline (see data_factory/ + README)
# ---------------------------------------------------------------------------
resource "azurerm_data_factory" "main" {
  name                = "${var.project_name}-adf"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
}

# ---------------------------------------------------------------------------
# Azure SQL — warehouse (serverless, auto-pause)
# ---------------------------------------------------------------------------
resource "azurerm_mssql_server" "main" {
  name                         = "${var.project_name}-sql"
  resource_group_name          = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  version                        = "12.0"
  administrator_login           = "sqladmin"
  administrator_login_password  = var.sql_admin_password
}

resource "azurerm_mssql_database" "warehouse" {
  name                        = "weatherpipeline"
  server_id                   = azurerm_mssql_server.main.id
  sku_name                    = "GP_S_Gen5_1" # General Purpose, Serverless, 1 vCore
  auto_pause_delay_in_minutes = 60
  min_capacity                = 0.5
}

resource "azurerm_mssql_firewall_rule" "allow_azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_mssql_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# ---------------------------------------------------------------------------
# Azure Function — transform (Blob-triggered on raw/)
# ---------------------------------------------------------------------------
resource "azurerm_storage_account" "function" {
  name                     = "${var.project_name}func"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

resource "azurerm_service_plan" "function" {
  name                = "${var.project_name}-plan"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = "Y1" # consumption plan
}

resource "azurerm_linux_function_app" "transform" {
  name                       = "${var.project_name}-transform"
  resource_group_name         = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  storage_account_name        = azurerm_storage_account.function.name
  storage_account_access_key  = azurerm_storage_account.function.primary_access_key
  service_plan_id             = azurerm_service_plan.function.id

  site_config {
    application_stack {
      python_version = "3.12"
    }
  }

  app_settings = {
    # TODO: build the real connection string once the SQL DB is reachable,
    # e.g. "Driver={ODBC Driver 18 for SQL Server};Server=tcp:<fqdn>,1433;
    #       Database=weatherpipeline;Uid=sqladmin;Pwd=<password>;Encrypt=yes;"
    SQL_CONNECTION_STRING = "TODO"
    ADLS_ACCOUNT_NAME     = azurerm_storage_account.datalake.name
  }
}

# TODO: front end — host frontend/index.html as a Static Web App, or behind
# an Azure Function HTTP endpoint that queries Azure SQL.
