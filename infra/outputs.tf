output "app_url" {
  value = "http://localhost:${var.app_port}"
}

output "docs_url" {
  value = "http://localhost:${var.app_port}/docs"
}

output "database_url" {
  # 127.0.0.1, not localhost: on Windows localhost tries IPv6 ::1 first and stalls before falling back
  value     = "postgresql://m2a:${var.db_password}@127.0.0.1:${var.db_port}/m2a"
  sensitive = true
}
