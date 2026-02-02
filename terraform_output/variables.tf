variable "project_id" { type = string }
variable "region"     { type = string  default = "europe-west1" }
variable "zone"       { type = string  default = "europe-west1-b" }

variable "allow_http"  { type = bool default = true }
variable "allow_https" { type = bool default = true }
variable "ssh_port"    { type = number default = 22 }