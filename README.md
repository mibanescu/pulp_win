pulp_win
========

Pulp plugin to handle Windows MSI packages

The plugin supports the following unit types:
* msi
* msm

Packages are being published in a repomd format (specific to yum repositories,
but extendable).

### Requirements

Admin extensions do not need additional tools.

Server extensions need msitools, which is available in Fedora. The Fedora 23
package has been confirmed to work on CentOS 7.

### Installation

Build the RPMs from spec file.

To enable the plugin, you will need to stop pulp services and migrate the
database, and then restart the services.

```
Example Usage:

    ~ $  pulp-admin win repo create --serve-http=true  --repo-id win-test-repo
    Successfully created repository [win-test-repo]
    
    ~ $  pulp-admin win repo uploads msi -f nxlog-ce-2.5.1089.msi --repo-id win-test-repo
    +----------------------------------------------------------------------+
                                  Unit Upload
    +----------------------------------------------------------------------+
    
    Extracting necessary metadata for each request...
    [==================================================] 100%
    Analyzing: nxlog-ce-2.5.1089.msi
    ... completed
    
    Creating upload requests on the server...
    [==================================================] 100%
    Initializing: nxlog-ce-2.5.1089.msi
    ... completed
    
    Starting upload of selected units. If this process is stopped through ctrl+c,
    the uploads will be paused and may be resumed later using the resume command or
    cancelled entirely using the cancel command.
    
    Uploading: nxlog-ce-2.5.1089.msi
    [==================================================] 100%
    3584000/3584000 bytes
    ... completed
    
    Importing into the repository...
    ... completed
    
    Deleting the upload request...
    ... completed
    
    ~ $  pulp-admin win repo publish run --repo-id win-test-repo 
    +----------------------------------------------------------------------+
                     Publishing Repository [win-test-repo]
    +----------------------------------------------------------------------+
    
    This command may be exited by pressing ctrl+c without affecting the actual
    operation on the server.
    
    Publishing packages...
    [==================================================] 100%
    Packages: 1/1 items
    ... completed
    
    Publishing repository over HTTP
    [-]
    ... completed

    ~ $  pulp-admin win repo content msi  --repo-id win-test-repo
    Productname:    NXLOG-CE
    Productversion: 2.5.1089
    Checksum:       06f3a9975ae920aa6058887cc5be55c5
    Checksumtype:   md5
```

