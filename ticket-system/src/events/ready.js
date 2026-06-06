const { REST, Routes } = require('discord.js');
const fs = require('fs');
const path = require('path');
require('dotenv').config();

module.exports = {
    name: 'ready',
    once: true,
    async execute(client) {
        console.log(`[READY] Logged in as ${client.user.tag} (Ticket System)`);
        
        const commands = [];
        const commandsPath = path.join(__dirname, '../commands');
        if (fs.existsSync(commandsPath)) {
            const commandFolders = fs.readdirSync(commandsPath);
            for (const folder of commandFolders) {
                const folderPath = path.join(commandsPath, folder);
                if (fs.statSync(folderPath).isDirectory()) {
                    const commandFiles = fs.readdirSync(folderPath).filter(file => file.endsWith('.js'));
                    for (const file of commandFiles) {
                        const command = require(`../commands/${folder}/${file}`);
                        if ('data' in command) {
                            commands.push(command.data.toJSON());
                        }
                    }
                }
            }
        }

        if (!process.env.DISCORD_TOKEN) return;

        const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);
        try {
            console.log(`[SLASH] Started refreshing ${commands.length} application (/) commands.`);
            const data = await rest.put(
                Routes.applicationCommands(client.user.id),
                { body: commands },
            );
            console.log(`[SLASH] Successfully reloaded ${data.length} application (/) commands.`);
        } catch (error) {
            console.error('[SLASH ERROR]', error);
        }
    },
};
