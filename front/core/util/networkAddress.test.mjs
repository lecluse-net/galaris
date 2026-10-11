import assert from 'node:assert/strict'
import test from 'node:test'
import { isPrivateHostname } from './networkAddress.ts'

test('local names and non-public IPs cannot serve as public webhook addresses', () => {
  for (const host of [
    'localhost', 'bot.localhost', 'LOCALHOST.', 'galaris', 'galaris.local', 'galaris.lan',
    'galaris.internal', 'galaris.home.arpa', 'galaris.test',
    '0.0.0.0', '127.0.0.2', '10.20.30.40', '192.168.1.5', '169.254.1.1',
    '172.16.0.1', '172.31.255.255', '100.64.0.1', '100.127.255.255',
    '[::1]', '[::]', '[fc00::1]', '[fd12::5]', '[fe80::1]',
    '[::ffff:192.168.1.1]', '[::ffff:7f00:1]',
  ]) assert.equal(isPrivateHostname(host), true, host)
})

test('public names and IPs do not trigger a private-address warning', () => {
  for (const host of [
    'galaris.example.com', 'galaris.example.com.', 'localhost.example.com',
    '8.8.8.8', '172.15.255.255', '172.32.0.1', '100.63.255.255', '100.128.0.1',
    '[2001:4860:4860::8888]', '[::ffff:808:808]',
  ]) assert.equal(isPrivateHostname(host), false, host)
})
