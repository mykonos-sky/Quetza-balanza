# Standard Proxmox VM set up
This will document what the standard will be for setting up virtual machines in Proxmox. This particular documentation will be have ranges for some of the set-up process since each operating system will have different requirements for functionality. I will be following [BarmineTech's][ProxmoxUbuntuSetup] guide on how to set up virtual machines in Proxmox and will be basing my documentation on it.

## OS Images
The typical operating systems that will be used are Linux distributions such as Debian, Ubuntu, Mint, etc. and occasionally WindowsOS. The ISO images will be stored in local(play). There will be both desktop and server versions of the operating systems mentioned.
### Prerequisite
Check to see if an image of the desired OS is installed onto Proxmox already. To check, go to **play** > **local(play)** > **ISO Images**. If the OS is not found there, you'll need to download an image of the OS from the distribution's official site and add it there.

## Creating a Virtual Machine
1. Click **Create VM** button on the top right corner.
2. Name the virtual machine in this standard (3 letter OS)-(use two words) Example: ubu_bashlearning.
    - This will help quickly gather basic information on the virtual machine. It will also serve to document what each virtual machine is running on and it's use
3. Click **Next**. The following page should have a dropdown menu that will show all the OS in the ISO Images section where the OS images were installed in. Select the OS the virtual machine will run.
4. Make sure that the **Type** is set to the correct type of OS. For example, if the virtual machine is running Ubuntu, make sure **Type:** is set to Linux.
5. Leave the rest as what's default, then click **Next**.
6. Leave the next page as default as well, then click **Next**.
7. Leave the next page as default as well, then click **Next**.
8.  For storage, you'll select **local-lvm**.
    - Note that at this the storage selection at this time but it is subject to change.
9.  Assign the **Disk Size** that is needed, then **Next**.
10. Type the number of cores needed. The number of cores needed is dependent on how the virtual machine will be used. If the virtual machine will be used as a NAS, for example, it will likely need 16 cores. If the virtual machine will be used as a server, it will need 2-6 cores. Leave the rest as default.
11. Next, type in the amount of RAM needed in GB. Similar to the previous step, the amount of RAM is depent on hpw the virtual machine will be used. 
12. In the next page, confirm that the information is correct and click **Finish**.

Once successful, Proxmox will create the virtual machine and it will appear on the left side with the given name.

## Reference Links
[ProxmoxUbuntuSetup]: https://youtu.be/5c7A5um03IM?si=sk8hiQSrdoikdIBG
Proxmox VM Set up: https://youtu.be/5c7A5um03IM?si=sk8hiQSrdoikdIBG
