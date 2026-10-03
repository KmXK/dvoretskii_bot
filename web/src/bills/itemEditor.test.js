import assert from 'node:assert/strict'
import test from 'node:test'

import {
  assignmentsFromPortions, buildDistributionCards, formatPortion,
  getAssignmentsTotal, getBillDistributionSizeError, getCardDistributionKey,
  getDistributionCardCount, getDistributionSizeError, getPersonAmounts, getPersonPortions, getUnassignedPortion,
  parsePortion, parsePriceMinor, parseQuantity, retainAssignmentsForQuantity,
} from './itemEditor.js'


test('unit price and quantity keep the two 8.50 portions separate', () => {
  const price = parsePriceMinor('8,50')
  const quantity = parseQuantity('2')
  const assignments = assignmentsFromPortions({ kirill: '1', dima: '1' })

  assert.equal(price * quantity, 1700)
  assert.equal(formatPortion(getAssignmentsTotal(assignments)), '2')
  assert.equal(formatPortion(getUnassignedPortion(quantity, assignments)), '0')
  assert.deepEqual(getPersonAmounts(assignments, price, 'kirill'), { kirill: 850, dima: 850 })
  assert.equal(formatPortion(getUnassignedPortion(1, assignments)), '-1')
})

test('numeric drafts stay invalid while empty instead of becoming one', () => {
  for (const draft of ['', ' ', '0', '-1', '1.5', '2abc', '1e3', '9007199254740992']) {
    assert.equal(parseQuantity(draft), null)
  }

  for (const draft of ['', '0', '-8.50', '8.505', '8.50abc', 'Infinity']) {
    assert.equal(parsePriceMinor(draft), null)
  }

  assert.equal(parsePriceMinor('8.50'), 850)
  assert.equal(parsePriceMinor('0,01'), 1)
  assert.equal(parsePriceMinor('1.15'), 115)
})

test('portions accept decimal and fractional input without rounding', () => {
  assert.equal(formatPortion(parsePortion('0,5')), '1/2')
  assert.equal(formatPortion(parsePortion('2/6')), '1/3')
  assert.equal(formatPortion(parsePortion('')), '0')
  assert.equal(parsePortion('1/0'), null)
  assert.equal(parsePortion('-1'), null)
  assert.equal(assignmentsFromPortions({ kirill: 'wrong' }), null)
  assert.deepEqual(assignmentsFromPortions({ kirill: '', dima: '1/3' }), [
    { unit_count: 1, denominator: 3, debtors: ['dima'] },
  ])
})

test('equal sharing previews the server rounding with the payer last', () => {
  const assignments = [{ unit_count: 1, denominator: 1, debtors: ['kirill', 'dima', 'alex'] }]

  assert.deepEqual(getPersonPortions(assignments), { kirill: '1/3', dima: '1/3', alex: '1/3' })
  assert.deepEqual(getPersonAmounts(assignments, 100, 'kirill'), { dima: 34, alex: 33, kirill: 33 })
})

test('editing a name or price retains explicit unassigned pieces without hiding the remainder', () => {
  const assignments = [
    { unit_count: 1, denominator: 2, debtors: ['kirill', 'dima'] },
    { unit_count: 1, denominator: 2, debtors: [] },
  ]
  const retained = retainAssignmentsForQuantity(assignments, 1, 1)
  const allocated = retained.filter((assignment) => assignment.debtors.length)

  assert.equal(retained, assignments)
  assert.equal(formatPortion(getUnassignedPortion(1, retained)), '0')
  assert.equal(formatPortion(getUnassignedPortion(1, allocated)), '1/2')
  assert.deepEqual(getPersonAmounts(retained, 101, 'kirill'), { dima: 26, kirill: 25 })
})

test('changing quantity drops stale unassigned placeholders and keeps allocated groups', () => {
  const assignments = [
    { unit_count: 1, denominator: 2, debtors: ['kirill', 'dima'] },
    { unit_count: 3, denominator: 2, debtors: [] },
  ]
  const retained = retainAssignmentsForQuantity(assignments, 2, 1)

  assert.deepEqual(retained, [assignments[0]])
  assert.equal(formatPortion(getUnassignedPortion(1, retained)), '1/2')
  assert.equal(formatPortion(getUnassignedPortion(1, retainAssignmentsForQuantity(assignments, 1, 1))), '-1')
})

function rebuild(transaction) {
  let sequence = 0
  const cards = buildDistributionCards([transaction], () => `card-${sequence += 1}`)
  const assignments = cards.map((card) => ({
    unit_count: 1,
    denominator: card.den,
    debtors: card.owner ? [card.owner] : [],
  }))
  return { cards, assignments }
}

test('a half assigned item leaves another half on the board', () => {
  const { cards, assignments } = rebuild({
    id: 'coffee',
    quantity: 1,
    assignments: [{ unit_count: 1, denominator: 2, debtors: ['kirill'] }],
  })

  assert.equal(cards.length, 2)
  assert.deepEqual(cards.map(({ owner, den }) => ({ owner, den })), [
    { owner: 'kirill', den: 2 },
    { owner: null, den: 2 },
  ])
  assert.equal(formatPortion(getAssignmentsTotal(assignments)), '1')
})

test('mixed fractions and explicit unassigned pieces conserve quantity on repeated reloads', () => {
  const transaction = {
    id: 'pizza',
    quantity: 2,
    assignments: [
      { unit_count: 1, denominator: 2, debtors: ['kirill'] },
      { unit_count: 1, denominator: 3, debtors: [] },
    ],
  }
  const first = rebuild(transaction)
  const second = rebuild({ ...transaction, assignments: first.assignments })

  assert.equal(formatPortion(getAssignmentsTotal(first.assignments)), '2')
  assert.equal(formatPortion(getAssignmentsTotal(second.assignments)), '2')
  assert.deepEqual(first.assignments, second.assignments)
  assert.deepEqual(first.cards.filter((card) => !card.owner).map((card) => card.den), [3, 1, 6])
})

test('shared assignments become one exact fraction per person on the board', () => {
  const { cards, assignments } = rebuild({
    id: 'pizza',
    quantity: 1,
    assignments: [{ unit_count: 1, denominator: 1, debtors: ['kirill', 'dima', 'alex'] }],
  })

  assert.equal(cards.length, 3)
  assert.equal(formatPortion(getAssignmentsTotal(assignments)), '1')
  assert.deepEqual(cards.map((card) => card.den), [3, 3, 3])
})

test('unchanged card distribution is recognized regardless of deck order and card IDs', () => {
  const cards = [
    { id: 'a', txId: 'coffee', den: 1, owner: 'kirill' },
    { id: 'b', txId: 'coffee', den: 2, owner: null },
    { id: 'c', txId: 'coffee', den: 2, owner: null },
  ]
  const reordered = [...cards].reverse().map((card) => ({ ...card, id: `new-${card.id}` }))
  const changed = cards.map((card) => card.id === 'b' ? { ...card, owner: 'dima' } : card)

  assert.equal(getCardDistributionKey(cards), getCardDistributionKey(reordered))
  assert.notEqual(getCardDistributionKey(cards), getCardDistributionKey(changed))
})

test('candidate count includes every encoded debtor piece and the exact remainder', () => {
  assert.equal(getDistributionCardCount(2, [{ unit_count: 2, denominator: 1, debtors: ['kirill', 'dima'] }]), 4n)
  assert.equal(getDistributionCardCount(2, [
    { unit_count: 1, denominator: 2, debtors: ['kirill'] },
    { unit_count: 1, denominator: 3, debtors: [] },
  ]), 4n)
  assert.equal(getDistributionCardCount(1, assignmentsFromPortions({ kirill: '0.333333' })), 1000000n)
  assert.equal(getDistributionCardCount(1, assignmentsFromPortions({ kirill: '0.000001' })), 1000000n)
})

test('simple thirds and the exact per-item limit stay supported', () => {
  const assignments = assignmentsFromPortions({ kirill: '1/3' })

  assert.equal(getDistributionCardCount(1, assignments), 3n)
  assert.equal(getDistributionSizeError(1, assignments), null)
  assert.equal(getDistributionSizeError(2000, []), null)
  assert.match(getDistributionSizeError(2001, []), /2000/)
  assert.equal(getBillDistributionSizeError([
    { quantity: 2000, assignments: [] },
    { quantity: 2000, assignments: [] },
  ]), null)
})

test('oversized fractions fail before allocating any cards or changing saved assignments', () => {
  const transaction = {
    id: 'tiny-fraction',
    item_name: 'Пицца',
    quantity: 1,
    assignments: assignmentsFromPortions({ kirill: '0.333333' }),
  }
  const original = JSON.stringify(transaction)
  let allocated = 0

  assert.match(getDistributionSizeError(transaction.quantity, transaction.assignments), /1\/3.*Поровну/)
  assert.throws(() => buildDistributionCards([
    { id: 'valid-first', quantity: 2, assignments: [] },
    transaction,
  ], () => {
    allocated += 1
    return String(allocated)
  }), /Пицца.*2000/)
  assert.equal(allocated, 0)
  assert.equal(JSON.stringify(transaction), original)
})
