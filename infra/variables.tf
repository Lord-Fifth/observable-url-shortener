variable "location" {
  description = "Azure region for every regional assessment resource."
  type        = string
  default     = "australiaeast"

  validation {
    condition     = var.location == "australiaeast"
    error_message = "Phase 4 resources must remain in australiaeast."
  }
}

variable "image_tag" {
  description = "Immutable Git SHA or assessment build identifier published to GHCR."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-z][0-9a-z._-]{6,127}$", var.image_tag))
    error_message = "image_tag must be a lowercase immutable container tag."
  }
}

variable "github_owner" {
  description = "Lowercase public GHCR namespace."
  type        = string
  default     = "lord-fifth"

  validation {
    condition     = can(regex("^[0-9a-z][0-9a-z-]*$", var.github_owner))
    error_message = "github_owner must be a lowercase GHCR namespace."
  }
}

