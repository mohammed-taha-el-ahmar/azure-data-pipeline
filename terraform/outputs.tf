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
