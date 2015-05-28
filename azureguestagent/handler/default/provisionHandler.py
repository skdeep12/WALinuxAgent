# Copyright 2014 Microsoft Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Requires Python 2.4+ and Openssl 1.0+
#

import os
import traceback
import azureguestagent.logger as logger
import azureguestagent.conf as conf
from azureguestagent.utils.osutil import CurrOSUtil
import azureguestagent.utils.shellutil as shellutil
import azureguestagent.utils.fileutil as fileutil

CustomDataFile="CustomData"

class ProvisionHandler(object):
    def process(self):
        #If provision is not enabled, return
        if not conf.GetSwitch("Provisioning.Enabled", True):
            logger.Info("Provisioning is disabled. Skip.")
            return

        provisoned = os.path.join(CurrOSUtil.GetLibDir(), "provisioned")
        if os.path.isfile(provisioned):
            return
        
        logger.Info("Start provisioning.")
        protocol = prot.GetDefaultProtocol()
        try:
            logger.Info("Provisioning image started")
            protocol.reportProvisionStatus("NotReady", 
                                           "Provisioning", 
                                           "Starting")
            self.provision()
            fileutil.SetFileContents(provisoned, "")
            thumbprint = self.regenerateSshHostKey(keyPairType)
            protocol.reportProvisionStatus(status="Ready",
                                           thumbprint = thumbprint)
        except ProvisionError as e:
            logger.Error("Provision failed: {0}", e)
            protocol.reportProvisionStatus(status="NotReady", subStatus=str(e))

    
    def regenerateSshHostKey(self):
        keyPairType = conf.Get("Provisioning.SshHostKeyPairType", "rsa")
        if self.config.getSwitch("Provisioning.RegenerateSshHostKeyPair"):
            shellutil.Run("rm -f /etc/ssh/ssh_host_*key*")
            shellutil.Run(("ssh-keygen -N '' -t {0} -f /etc/ssh/ssh_host_{1}_key"
                           "").format(keyPairType, keyPairType))
        thumbprint = self.getSshHostKeyThumbprint(keyPairType)
        return thumbprint

    def getSshHostKeyThumbprint(self, keyPairType):
        cmd = "ssh-keygen -lf /etc/ssh/ssh_host_{0}_key.pub".format(keyPairType)
        ret = shellutil.RunGetOutput(cmd)
        if ret[0] == 0:
            return ret[1].rstrip().split()[1].replace(':', '')
        else:
            raise ProvisionError(("Failed to generate ssh host key: "
                                  "ret={0}, out= {1}").format(ret[0], ret[1]))
            

    def provision(self):
        ovfenv = self.copyOvf()
        password = ovfenv.getUserPassword()
        ovfenv.clearUserPassword()

        CurrOSUtil.SetHostname(ovfenv.getComputerName())
        CurrOSUtil.PublishHostname(ovfenv.getComputerName())
        CurrOSUtil.UpdateUserAccount(ovfenv.getUserName(), password)

        if password is not None:
            userSalt = conf.GetSwitch("Provision.UseSalt", True)
            saltType = conf.GetSwitch("Provision.SaltType", 6)
            CurrOSUtil.ChangePassword(ovfenv.getUserName(), password)

        CurrOSUtil.ConfigSshd(ovfenv.getDisableSshPasswordAuthentication())

        #Disable selinux temporary
        sel = CurrOSUtil.IsSelinuxRunning()
        if sel:
            CurrOSUtil.SetSelinuxEnforce(0)

        self.deploySshPublicKeys(ovfenv)
        self.deploySshKeyPairs(ovfenv)
        self.saveCustomData(ovfenv)

        if sel:
            CurrOSUtil.SetSelinuxEnforce(1)

        CurrOSUtil.RestartSshService()

        if self.config.getSwitch("Provisioning.DeleteRootPassword"):
            CurrOSUtil.DeleteRootPassword()

    def copyOvf(self):
        """
        Copy ovf env file from dvd to hard disk. 
        Remove password before save it to the disk
        """
        CurrOSUtil.MountDvd()

        ovfFile = CurrOSUtil.GetOvfEnvPathOnDvd()
        if not os.path.isfile(ovfFile):
            raise ProvisionError("Missing ovf-env.xml")

        ovfxml = fileutil.GetFileContents(ovfFile, removeBom=True)
        ovfenv = OvfEnv(ovfxml)
        ovfxml = re.sub("<UserPassword>.*?<", "<UserPassword>*<", ovfxml)
        ovfFilePath = os.path.join(CurrOSUtil.GetLibDir(), OvfFileName)
        fileutil.SetFileContents(ovfFilePath, ovfxml)

        CurrOSUtil.UmountDvd()
        return ovfenv

    def saveCustomData(self, ovfenv):
        customData = ovfenv.getCustomData()
        if customData is None:
            return
        #TODO  port Abel's fix to decoding custom data
        libDir = CurrOSUtil.GetLibDir()
        fileutil.SetFileContents(os.path.join(libDir, CustomDataFile), 
                                 CurrOSUtil.TranslateCustomData(customData))

    def deploySshPublicKeys(self, ovfenv):
        for thumbprint, path in ovfenv.getSshPublicKeys():
            CurrOSUtil.DeploySshPublicKey(ovfenv.getUserName(), thumbprint, path)
    
    def deploySshKeyPairs(self, ovfenv):
        for thumbprint, path in ovfenv.getSshKeyPairs():
            CurrOSUtil.DeploySshKeyPair(ovfenv.getUserName(), thumbprint, path)
   
