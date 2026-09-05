# Module Proxmox — étapes A.1 à A.7 de clone-vm-node.sh, en déclaratif (ticket 9).
# Le module s'arrête quand la machine est démarrée et adressée : l'attente SSH
# est du ressort du driver, la configuration (A.10+) de configure-node.sh.
#
# Credentials : PROXMOX_VE_ENDPOINT / PROXMOX_VE_API_TOKEN en environnement du
# process tofu (posés par le driver depuis Harpocrate) — jamais dans ce fichier.

terraform {
  backend "pg" {}
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.84"
    }
  }
}

provider "proxmox" {
  # endpoint et api_token viennent de l'environnement (PROXMOX_VE_*).
}

# ─── Entrées — la MachineSpec, traduite en variables ─────────────────────────

variable "name" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$", var.name))
    error_message = "Nom DNS-safe attendu (^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$)."
  }
}
variable "cpu" { type = number }
variable "memory_mb" { type = number }
variable "disk_gb" { type = number }
variable "user" { type = string }
variable "ssh_authorized_keys" { type = list(string) }

variable "network_mode" {
  type = string
  validation {
    condition     = contains(["dhcp", "static"], var.network_mode)
    error_message = "network_mode : dhcp ou static."
  }
}
variable "network_address" {
  type    = string
  default = ""
}
variable "network_gateway" {
  type    = string
  default = ""
}
variable "network_dns" {
  type    = string
  default = ""
}

# ─── Entrées — la section provider (opaque pour le portail, pas pour nous) ───

variable "node" {
  type        = string
  description = "Nœud Proxmox cible (ex. pve)."
}
variable "template_vmid" {
  type        = number
  description = "VMID du template cloud-init à cloner."
}
variable "vmid" {
  type        = number
  default     = 0
  description = "VMID demandé ; 0 = attribué par Proxmox."
}
variable "storage" {
  type    = string
  default = ""
}
variable "bridge" {
  type    = string
  default = "vmbr0"
}
# x86-64-v3 par défaut, pas kvm64 : les binaires compilés avec Bun (dont
# `claude`) exigent AVX, que kvm64 masque. `host` reste opt-in : il expose
# /dev/kvm mais épingle la VM au CPU exact de son hôte (plus de migration).
variable "cpu_type" {
  type    = string
  default = "x86-64-v3"
  validation {
    condition     = contains(["x86-64-v3", "host"], var.cpu_type)
    error_message = "cpu_type : x86-64-v3 ou host (kvm64 masque AVX, volontairement absent)."
  }
}

# ─── A.1 — Unicité du VMID à l'échelle du CLUSTER ────────────────────────────
# `qm list` ne voit que le nœud local et rate un VMID pris ailleurs (le clone
# échouerait alors sur « rename ... failed: File exists », APRÈS création
# partielle). Le data source liste tout le cluster : on échoue proprement,
# avant toute création.
data "proxmox_virtual_environment_vms" "cluster" {}

# ─── A.2 → A.7 — Clone, ressources, disque, cloud-init, boot ─────────────────

resource "proxmox_virtual_environment_vm" "machine" {
  name      = var.name
  node_name = var.node
  vm_id     = var.vmid > 0 ? var.vmid : null

  lifecycle {
    precondition {
      condition = var.vmid == 0 || !contains(
        [for vm in data.proxmox_virtual_environment_vms.cluster.vms : vm.vm_id],
        var.vmid,
      )
      error_message = "VMID déjà utilisé dans le cluster (VM ou template) — aucune machine créée."
    }
  }

  clone {
    vm_id = var.template_vmid
    full  = true
    # Vide = même stockage que le template (comportement du script).
    datastore_id = var.storage != "" ? var.storage : null
  }

  cpu {
    cores = var.cpu
    type  = var.cpu_type
  }

  memory {
    dedicated = var.memory_mb
  }

  # Disque OS : taille ABSOLUE (contrat de la spec) — le delta du script était
  # un artefact du template. Redimensionné à la hausse avant le premier boot.
  disk {
    interface    = "scsi0"
    size         = var.disk_gb
    datastore_id = var.storage != "" ? var.storage : null
  }

  network_device {
    bridge = var.bridge
  }

  # L'agent AVANT le boot, sinon la détection d'IP retombe sur le ping-sweep.
  agent {
    enabled = true
  }

  # Sans onboot, un reboot du host PVE laisse le nœud éteint et indisponible.
  on_boot = true
  started = true

  initialization {
    datastore_id = var.storage != "" ? var.storage : null

    user_account {
      username = var.user
      keys     = var.ssh_authorized_keys
    }

    ip_config {
      ipv4 {
        address = var.network_mode == "dhcp" ? "dhcp" : var.network_address
        gateway = var.network_mode == "static" ? var.network_gateway : null
      }
    }

    dynamic "dns" {
      for_each = var.network_dns != "" ? [var.network_dns] : []
      content {
        servers = [dns.value]
      }
    }
  }
}

# ─── Sorties — ce que le descripteur consomme ────────────────────────────────

output "vmid" {
  value = proxmox_virtual_environment_vm.machine.vm_id
}

output "node" {
  value = var.node
}

# Première IPv4 non-loopback rapportée par l'agent QEMU. Si l'agent manque au
# template, la liste est vide : le driver le signale explicitement (pas de
# ping-sweep ici — le repli du script reste disponible via le chemin legacy).
output "ipv4" {
  value = try(
    [for ip in flatten(proxmox_virtual_environment_vm.machine.ipv4_addresses) : ip
    if ip != "127.0.0.1"][0],
    ""
  )
}
