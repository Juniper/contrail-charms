/^[[:blank:]]*(iface|mapping|auto|allow-[^ ]+|source) / {
    s_iface = 0
}

$1 == "auto" { print $2 >> auto_interfaces; next }

$1 == "iface" {
    s_iface = 1
    iface = $2
    next
}

s_iface == 1 {
    if ($1 == "bridge_ports") {
        for (i = 2; i <= NF; i++) {
            if ($i == interface) {
                print iface >> bridge_interfaces
                break
            }
        }
    }
}
