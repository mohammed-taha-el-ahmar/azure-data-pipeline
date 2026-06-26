output "data_lake_account" {
  value = azurerm_storage_account.datalake.name
}

output "sql_server_fqdn" {
  value = azurerm_mssql_server.main.fully_qualified_domain_name
}

output "data_factory_name" {
  value = azurerm_data_factory.main.name
}

output "transform_function_app" {
  value = azurerm_linux_function_app.transform.name
}

output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "api_base_url" {
  description = "Base URL for the Azure Function HTTP API"
  value       = "https://${azurerm_linux_function_app.transform.default_hostname}/api"
}

output "frontend_url" {
  description = "URL of the Static Web App hosting the dashboard"
  value       = azurerm_static_web_app.frontend.default_host_name
}
