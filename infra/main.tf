locals {
  root = abspath("${path.module}/..")
  src = sort(concat(
    tolist(fileset(local.root, "m2a/**/*.py")),
    tolist(fileset(local.root, "m2a/web/*.html")),
    tolist(fileset(local.root, "memory/*.md")),
    ["requirements.txt", "Dockerfile"],
  ))
  src_hash = sha1(join("", [for f in local.src : filesha1("${local.root}/${f}")]))
}

resource "docker_network" "m2a" {
  name = "m2a-net"
}

resource "docker_volume" "pgdata" {
  name = "m2a-pgdata"
}

resource "docker_image" "postgres" {
  name         = "postgres:16-alpine"
  keep_locally = true
}

resource "docker_container" "db" {
  name    = "m2a-db"
  image   = docker_image.postgres.image_id
  restart = "unless-stopped"
  env = [
    "POSTGRES_USER=m2a",
    "POSTGRES_PASSWORD=${var.db_password}",
    "POSTGRES_DB=m2a",
  ]
  networks_advanced {
    name = docker_network.m2a.name
  }
  volumes {
    volume_name    = docker_volume.pgdata.name
    container_path = "/var/lib/postgresql/data"
  }
  ports {
    internal = 5432
    external = var.db_port
  }
  healthcheck {
    test     = ["CMD-SHELL", "pg_isready -U m2a -d m2a"]
    interval = "5s"
    timeout  = "3s"
    retries  = 12
  }
  wait = true
}

resource "docker_image" "app" {
  name = "meeting-to-action:${substr(local.src_hash, 0, 12)}"
  build {
    context = local.root
  }
  triggers = {
    src = local.src_hash
  }
}

resource "docker_container" "app" {
  name    = "m2a-app"
  image   = docker_image.app.image_id
  restart = "unless-stopped"
  env = [
    "DATABASE_URL=postgresql://m2a:${var.db_password}@${docker_container.db.name}:5432/m2a",
    "ANTHROPIC_API_KEY=${var.anthropic_api_key}",
    "CLAUDE_MODEL=${var.claude_model}",
    "APP_ACCESS_KEY=${var.app_access_key}",
  ]
  networks_advanced {
    name = docker_network.m2a.name
  }
  ports {
    internal = 8080
    external = var.app_port
  }
  wait         = true
  wait_timeout = 90
}
