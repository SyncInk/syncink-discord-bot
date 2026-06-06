const sqlite3 = require('sqlite3').verbose();
const { open } = require('sqlite');
const mongoose = require('mongoose');
const config = require('../../config');
require('dotenv').config();

let sqliteDb;

async function initDatabase() {
    if (config.database.useMongo) {
        if (!process.env.MONGO_URI) {
            console.error('[DB] MONGO_URI is missing in .env file!');
            process.exit(1);
        }
        await mongoose.connect(process.env.MONGO_URI, {
            useNewUrlParser: true,
            useUnifiedTopology: true
        });
        console.log('[DB] Connected to MongoDB');
    } else {
        sqliteDb = await open({
            filename: './database.sqlite',
            driver: sqlite3.Database
        });

        await sqliteDb.exec(`
            CREATE TABLE IF NOT EXISTS tickets (
                channelId TEXT PRIMARY KEY,
                ticketId TEXT,
                creatorId TEXT,
                type TEXT,
                claimerId TEXT,
                status TEXT,
                createdAt INTEGER,
                closedAt INTEGER
            )
        `);
        console.log('[DB] Connected to SQLite');
    }
}

// Helper functions that abstract away the DB choice
async function createTicket(data) {
    if (config.database.useMongo) {
        const Ticket = getMongoModel();
        await new Ticket(data).save();
    } else {
        await sqliteDb.run(
            'INSERT INTO tickets (channelId, ticketId, creatorId, type, claimerId, status, createdAt, closedAt) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            [data.channelId, data.ticketId, data.creatorId, data.type, data.claimerId, data.status, data.createdAt, data.closedAt]
        );
    }
}

async function getTicket(channelId) {
    if (config.database.useMongo) {
        const Ticket = getMongoModel();
        return await Ticket.findOne({ channelId });
    } else {
        return await sqliteDb.get('SELECT * FROM tickets WHERE channelId = ?', [channelId]);
    }
}

async function updateTicket(channelId, updateData) {
    if (config.database.useMongo) {
        const Ticket = getMongoModel();
        await Ticket.updateOne({ channelId }, updateData);
    } else {
        const sets = [];
        const values = [];
        for (const [key, value] of Object.entries(updateData)) {
            sets.push(`${key} = ?`);
            values.push(value);
        }
        values.push(channelId);
        if (sets.length > 0) {
            await sqliteDb.run(`UPDATE tickets SET ${sets.join(', ')} WHERE channelId = ?`, values);
        }
    }
}

// Lazy load mongoose model
let TicketModel;
function getMongoModel() {
    if (!TicketModel) {
        const schema = new mongoose.Schema({
            channelId: { type: String, required: true, unique: true },
            ticketId: { type: String, required: true },
            creatorId: { type: String, required: true },
            type: { type: String, required: true },
            claimerId: { type: String, default: null },
            status: { type: String, default: 'open' },
            createdAt: { type: Number, default: Date.now },
            closedAt: { type: Number, default: null }
        });
        TicketModel = mongoose.model('Ticket', schema);
    }
    return TicketModel;
}

module.exports = {
    initDatabase,
    createTicket,
    getTicket,
    updateTicket
};
