const { REST, Routes } = require('discord.js');
require('dotenv').config();

const token = process.env.DISCORD_TOKEN;
const rest = new REST({ version: '10' }).setToken(token);

async function clearCommands() {
    try {
        console.log('Fetching application id...');
        const app = await rest.get(Routes.oauth2CurrentApplication());
        const clientId = app.id;
        
        console.log(`Clearing global commands for ${clientId}...`);
        await rest.put(Routes.applicationCommands(clientId), { body: [] });
        console.log('Global commands cleared.');

        // For the guild commands
        const GUILD_ID = '11513075101992747158'; // The bot's ID from earlier, wait, I need the guild ID.
        // Actually, I can fetch the guilds the bot is in, and clear commands for all of them.
        const guilds = await rest.get(Routes.userGuilds());
        for (const guild of guilds) {
            console.log(`Clearing commands for guild ${guild.id}...`);
            await rest.put(Routes.applicationGuildCommands(clientId, guild.id), { body: [] });
        }
        
        console.log('All commands cleared successfully!');
    } catch (error) {
        console.error(error);
    }
}

clearCommands();
