Sample bundle to deploy Contrail with K8s in nested mode.
Nested mode means that this bundle can be applied to deploy kubernetes with Contrail CNI support in VM-s that are run on top of OpenStack+Contrail cluster.
In nested mode charms deploy just CNI and kubemanager from Contrail components.
To deploy bundle to existing machines you can use next command:
`juju deploy --map-machines=existing,0=0,5=1 ./bundle.yaml`
Where ids are `bundle-id=existing-id`.