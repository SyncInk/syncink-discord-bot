const { ModalBuilder, TextInputBuilder, TextInputStyle, ActionRowBuilder, ChannelType, PermissionFlagsBits, EmbedBuilder, ButtonBuilder, ButtonStyle, ComponentType } = require('discord.js');
const discordTranscripts = require('discord-html-transcripts');
const config = require('../../config');
const db = require('./database');

async function handleSelectMenu(interaction, client) {
    if (interaction.customId === 'ticket_select_type') {
        const selectedValue = interaction.values[0];
        const optionData = config.ticketOptions.find(o => o.value === selectedValue);
        
        if (!optionData) return interaction.reply({ content: 'Invalid ticket type.', ephemeral: true });

        const modal = new ModalBuilder()
            .setCustomId(`ticket_modal_${selectedValue}`)
            .setTitle(optionData.label.substring(0, 45));

        const reasonInput = new TextInputBuilder()
            .setCustomId('ticket_reason')
            .setLabel("Reason for opening ticket")
            .setStyle(TextInputStyle.Short)
            .setRequired(true);

        const detailsInput = new TextInputBuilder()
            .setCustomId('ticket_details')
            .setLabel("Additional Details")
            .setStyle(TextInputStyle.Paragraph)
            .setRequired(false);

        modal.addComponents(
            new ActionRowBuilder().addComponents(reasonInput),
            new ActionRowBuilder().addComponents(detailsInput)
        );

        await interaction.showModal(modal);
    }
}

async function handleModalSubmit(interaction, client) {
    if (interaction.customId.startsWith('ticket_modal_')) {
        await interaction.deferReply({ ephemeral: true });

        const typeValue = interaction.customId.replace('ticket_modal_', '');
        const optionData = config.ticketOptions.find(o => o.value === typeValue);
        const reason = interaction.fields.getTextInputValue('ticket_reason');
        const details = interaction.fields.getTextInputValue('ticket_details') || 'No additional details provided.';
        
        const guild = interaction.guild;
        const categoryId = config.ticketCategoryId;
        const category = guild.channels.cache.get(categoryId);

        // Permissions array
        const permissionOverwrites = [
            {
                id: guild.id,
                deny: [PermissionFlagsBits.ViewChannel],
            },
            {
                id: interaction.user.id,
                allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages, PermissionFlagsBits.ReadMessageHistory],
            }
        ];

        // Add staff roles permissions
        const staffRoles = [...config.staffRoleIds, ...config.adminRoleIds, ...config.ownerRoleIds];
        for (const roleId of staffRoles) {
            if (roleId && guild.roles.cache.has(roleId)) {
                permissionOverwrites.push({
                    id: roleId,
                    allow: [PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages, PermissionFlagsBits.ReadMessageHistory],
                });
            }
        }

        let prefix = 'ticket';
        if (typeValue === 'bug_report') prefix = 'bug';
        else if (typeValue === 'user_report') prefix = 'report';
        else if (typeValue === 'general_request') prefix = 'help';

        const channelName = `${prefix}-${interaction.user.username}`;

        try {
            const channel = await guild.channels.create({
                name: channelName,
                type: ChannelType.GuildText,
                parent: category || null,
                permissionOverwrites
            });

            const ticketId = Math.floor(Math.random() * 100000).toString();

            // Store in DB
            await db.createTicket({
                channelId: channel.id,
                ticketId,
                creatorId: interaction.user.id,
                type: typeValue,
                claimerId: null,
                status: 'open',
                createdAt: Date.now(),
                closedAt: null
            });

            // Create thread
            const threadName = `${prefix} discussion`;
            const thread = await channel.threads.create({
                name: threadName,
                autoArchiveDuration: 1440,
                type: ChannelType.PrivateThread,
                reason: 'Ticket discussion thread'
            });

            // Welcome message embed
            const welcomeEmbed = new EmbedBuilder()
                .setTitle(`Ticket: ${optionData.label}`)
                .setColor(config.colors.primary)
                .setDescription(`Thank you for reaching out, <@${interaction.user.id}>!\nSupport staff will be with you shortly.\n\n**Reason:** ${reason}\n**Details:** ${details}`)
                .addFields(
                    { name: 'Claimed By', value: 'No one has claimed this ticket yet.' }
                )
                .setTimestamp();

            const closeBtn = new ButtonBuilder().setCustomId('ticket_btn_close').setLabel('🔒 Close').setStyle(ButtonStyle.Danger);
            const claimBtn = new ButtonBuilder().setCustomId('ticket_btn_claim').setLabel('📝 Claim').setStyle(ButtonStyle.Success);
            const transferBtn = new ButtonBuilder().setCustomId('ticket_btn_transfer').setLabel('🔁 Transfer').setStyle(ButtonStyle.Secondary);

            const row = new ActionRowBuilder().addComponents(closeBtn, claimBtn, transferBtn);

            await channel.send({ content: `<@${interaction.user.id}>`, embeds: [welcomeEmbed], components: [row] });
            
            await logTicketAction(client, guild, 'Ticket Created', `User: <@${interaction.user.id}>\nChannel: <#${channel.id}>\nType: ${optionData.label}`, config.colors.success);

            await interaction.editReply(`Your ticket has been created: <#${channel.id}>`);
        } catch (error) {
            console.error('[TICKET CREATE ERROR]', error);
            await interaction.editReply('Failed to create ticket. Please check permissions and configuration.');
        }
    }
}

async function handleButton(interaction, client) {
    const { customId, channel, user, guild } = interaction;
    const ticket = await db.getTicket(channel.id);

    if (!ticket) {
        if (customId.startsWith('ticket_btn_')) {
            return interaction.reply({ content: 'This channel is not registered as a ticket in the database.', ephemeral: true });
        }
        return;
    }

    // Check staff permissions
    const isStaff = [...config.staffRoleIds, ...config.adminRoleIds, ...config.ownerRoleIds].some(roleId => interaction.member.roles.cache.has(roleId)) || interaction.member.permissions.has(PermissionFlagsBits.Administrator);

    if (customId === 'ticket_btn_claim') {
        if (!isStaff) return interaction.reply({ content: 'Only staff members can claim tickets.', ephemeral: true });
        if (ticket.claimerId) return interaction.reply({ content: `This ticket is already claimed by <@${ticket.claimerId}>.`, ephemeral: true });

        await db.updateTicket(channel.id, { claimerId: user.id });

        const embed = interaction.message.embeds[0];
        const newEmbed = EmbedBuilder.from(embed);
        
        newEmbed.data.fields[0] = { name: 'Claimed By', value: `<@${user.id}>` };

        await interaction.update({ embeds: [newEmbed] });

        const claimEmbed = new EmbedBuilder()
            .setColor(config.colors.success)
            .setDescription(`Thank you for your patience <@${ticket.creatorId}>\n<@${user.id}> will be with you shortly.`);
        
        await channel.send({ embeds: [claimEmbed] });
        await logTicketAction(client, guild, 'Ticket Claimed', `Channel: <#${channel.id}>\nClaimed By: <@${user.id}>`, config.colors.primary);

    } else if (customId === 'ticket_btn_close') {
        if (!isStaff && user.id !== ticket.creatorId) return interaction.reply({ content: 'You do not have permission to close this ticket.', ephemeral: true });

        await interaction.reply({ content: 'Closing ticket in 5 seconds...' });

        // Generate transcript
        const transcript = await discordTranscripts.createTranscript(channel, {
            limit: -1,
            returnType: 'attachment',
            fileName: `${channel.name}-transcript.html`,
            saveImages: true,
            poweredBy: false
        });

        await db.updateTicket(channel.id, { status: 'closed', closedAt: Date.now() });

        await logTicketAction(client, guild, 'Ticket Closed', `Channel: ${channel.name}\nClosed By: <@${user.id}>\nCreator: <@${ticket.creatorId}>`, config.colors.error, transcript);

        // Try to DM the user
        try {
            const creator = await client.users.fetch(ticket.creatorId);
            if (creator) {
                const dmEmbed = new EmbedBuilder()
                    .setTitle('Ticket Closed')
                    .setDescription(`Your ticket **${channel.name}** in **${guild.name}** has been closed.\nAttached is your transcript.`)
                    .setColor(config.colors.primary);
                await creator.send({ embeds: [dmEmbed], files: [transcript] });
            }
        } catch (e) {
            console.log('Could not DM user transcript.');
        }

        setTimeout(() => {
            channel.delete().catch(() => {});
        }, 5000);

    } else if (customId === 'ticket_btn_transfer') {
        if (!isStaff) return interaction.reply({ content: 'Only staff can transfer tickets.', ephemeral: true });
        // Can implement a select menu to choose a role/user to transfer to
        await interaction.reply({ content: 'Transfer feature is currently limited. Mention another staff member to assist.', ephemeral: true });
    }
}

async function logTicketAction(client, guild, title, description, color, attachment = null) {
    if (!config.logChannelId) return;
    const logChannel = guild.channels.cache.get(config.logChannelId);
    if (!logChannel) return;

    const embed = new EmbedBuilder()
        .setTitle(title)
        .setDescription(description)
        .setColor(color)
        .setTimestamp();

    const payload = { embeds: [embed] };
    if (attachment) payload.files = [attachment];

    try {
        await logChannel.send(payload);
    } catch (e) {
        console.error('[LOG ERROR]', e);
    }
}

module.exports = {
    handleSelectMenu,
    handleModalSubmit,
    handleButton
};
