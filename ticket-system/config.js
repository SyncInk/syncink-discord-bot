module.exports = {
    // Ticket System Category ID
    ticketCategoryId: 'REPLACE_WITH_CATEGORY_ID',
    
    // Log Channel ID
    logChannelId: 'REPLACE_WITH_LOG_CHANNEL_ID',
    
    // Role IDs that can manage tickets
    staffRoleIds: ['REPLACE_WITH_STAFF_ROLE_ID'],
    adminRoleIds: ['REPLACE_WITH_ADMIN_ROLE_ID'],
    ownerRoleIds: ['REPLACE_WITH_OWNER_ROLE_ID'],

    // Visual Settings
    colors: {
        primary: '#9B59B6', // Dark purple/pink gradient theme
        success: '#2ECC71',
        error: '#E74C3C',
        log: '#2C2F33'
    },

    // Ticket Options
    ticketOptions: [
        {
            label: 'General Request',
            description: 'request help with something in general',
            value: 'general_request',
            emoji: '🔮' // Replace with your custom emoji ID if desired, e.g. '<:shield_fire:123456789>'
        },
        {
            label: 'User Report',
            description: 'report a misbehaving user to the moderators',
            value: 'user_report',
            emoji: '👤'
        },
        {
            label: 'Bug Report',
            description: 'report a bug to the developers',
            value: 'bug_report',
            emoji: '🐛'
        },
        {
            label: 'Staff Abuse',
            description: 'report a misbehaving staff member to the admins',
            value: 'staff_abuse',
            emoji: '🛡️'
        },
        {
            label: 'Other',
            description: 'something else that is not listed above',
            value: 'other_request',
            emoji: '🔧'
        },
        {
            label: 'Owner Contact',
            description: 'only for serious matters and community inquiries',
            value: 'owner_contact',
            emoji: '👑'
        }
    ],

    // Database Settings
    database: {
        // Switch to true to use MongoDB instead of SQLite
        useMongo: false
    }
};
