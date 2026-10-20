variable "docker_host" {
  description = "Docker engine endpoint (Docker Desktop on Windows uses a named pipe)"
  type        = string
  default     = "npipe:////./pipe/docker_engine"
}

variable "anthropic_api_key" {
  description = "Claude API key, passed to the app container only"
  type        = string
  sensitive   = true
}

variable "db_password" {
  description = "Password for the m2a Postgres user"
  type        = string
  sensitive   = true
}

variable "app_access_key" {
  description = "Optional X-API-Key the web page and API require; empty disables the gate"
  type        = string
  sensitive   = true
  default     = ""
}

variable "claude_model" {
  type    = string
  default = "claude-sonnet-5-5"
}

variable "app_port" {
  type    = number
  default = 8090
}

variable "db_port" {
  description = "Host port for Postgres, handy for psql and the Postgres tests"
  type        = number
  default     = 5434
}
