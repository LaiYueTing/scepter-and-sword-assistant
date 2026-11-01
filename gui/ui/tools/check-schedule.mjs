// 驗任務卡時間欄的文字轉換：顯示與寫回要對得起來。
import assert from 'node:assert/strict'
import { formatWeekly, parseTimes } from '../src/data/schedule.js'

const chaos = ['週日 10:00', '週日 14:00', '週日 21:30']
assert.equal(formatWeekly(chaos), '週日 10:00、14:00、21:30')
assert.deepEqual(parseTimes(formatWeekly(chaos), true), chaos)

const mixed = ['週一 08:00', '週一 09:00', '週三 09:00']
assert.equal(formatWeekly(mixed), '週一 08:00、09:00、週三 09:00')
assert.deepEqual(parseTimes(formatWeekly(mixed), true), mixed)

assert.deepEqual(parseTimes('週一 08:05', true), ['週一 08:05'])
assert.deepEqual(parseTimes('週一08:05，週二 09:00', true), ['週一 08:05', '週二 09:00'])
assert.deepEqual(parseTimes('週一', true), ['週一'])
assert.deepEqual(parseTimes('週一 週二 08:00', true), ['週一', '週二 08:00'])
assert.deepEqual(parseTimes('08:00', true), ['08:00'])
assert.deepEqual(parseTimes('', true), [])

assert.deepEqual(parseTimes('12:30、21:00', false), ['12:30', '21:00'])
assert.deepEqual(parseTimes('12:30 21:00', false), ['12:30', '21:00'])

console.log('check-schedule 通過')
