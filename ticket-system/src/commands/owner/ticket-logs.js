const { SlashCommandBuilder, PermissionFlagsBits, ChannelType } = require('discord.js');
const db = require('../../utils/database');

module.exports = {
    data: new SlashCommandBuilder()
        .setName('ticket-logs')
        .setDescription('Set the channel for ticket logs and transcripts')
        .addChannelOption(opt => opt.setName('channel').setDescription('Log channel').setRequired(true).addChannelTypes(ChannelType.GuildText))
        .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
    
    async execute(interaction) {
        const channel = interaction.options.getChannel('channel');
        await db.updateGuildConfig(interaction.guild.id, { logChannelId: channel.id });
        
        await interaction.reply({ content: `✅ Ticket logs will now be sent to <#${channel.id}>`, ephemeral: true });
    },
};
