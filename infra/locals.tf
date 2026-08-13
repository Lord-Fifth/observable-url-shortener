locals {
  service_prefix  = "ous"
  database_name   = "url-shortener"
  mappings_name   = "url_mappings"
  events_name     = "redirect_events"
  image_namespace = "ghcr.io/${var.github_owner}"

  shortener_image = "${local.image_namespace}/observable-url-shortener-shortener:${var.image_tag}"
  resolver_image  = "${local.image_namespace}/observable-url-shortener-resolver:${var.image_tag}"

  common_tags = {
    application = "observable-url-shortener"
    assessment  = "ase-part-2"
    managed-by  = "terraform"
  }
}

