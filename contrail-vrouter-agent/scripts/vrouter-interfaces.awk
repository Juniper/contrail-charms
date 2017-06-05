function strip(s)
{
    sub(/^[[:blank:]]+/, "", s)
    sub(/[[:blank:]]+$/, "", s)
    return s
}

/^[[:blank:]]*(iface|mapping|auto|allow-[^ ]+|source) / {
    s_iface = 0; iface = 0
}

$0 ~ "^[[:blank:]]*auto (" interface "|vhost0)[[:blank:]]*$" { print "#" $0; next }

$0 ~ "^[[:blank:]]*iface (" interface "|vhost0) " {
    s_iface = 1
    if ($2 == interface) {
        iface = 1
        print "iface", interface, $3, "manual" > interface_cfg
        print "iface vhost0", $3, $4 > vrouter_cfg
    }
    print "#" $0
    next
}

s_iface == 1 {
    if (iface == 1) {
        if (match($1, "^address|netmask|broadcast|metric|gateway$")) {
            cfg = vrouter_cfg
        } else {
            cfg = interface_cfg
        }
        print "    " strip($0) > cfg
    }
    print "#" $0
    next
}

{ print $0 }
