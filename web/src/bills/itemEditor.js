function fraction(numerator, denominator = 1n) {
  let left = numerator < 0n ? -numerator : numerator
  let right = denominator
  while (right) {
    [left, right] = [right, left % right]
  }

  const divisor = left || 1n
  return { numerator: numerator / divisor, denominator: denominator / divisor }
}

export const MAX_DISTRIBUTION_CARDS = 2000

export function addPortions(left, right) {
  return fraction(
    left.numerator * right.denominator + right.numerator * left.denominator,
    left.denominator * right.denominator
  )
}

export function formatPortion(value) {
  return value.denominator === 1n ? String(value.numerator) : `${value.numerator}/${value.denominator}`
}

export function parseQuantity(value) {
  const text = String(value).trim()
  const parsed = Number(text)
  return /^\d+$/.test(text) && Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
}

export function parsePriceMinor(value) {
  const match = /^(\d+)(?:[.,](\d{0,2}))?$/.exec(String(value).trim())
  if (!match) {
    return null
  }

  const amount = BigInt(match[1]) * 100n + BigInt((match[2] || '').padEnd(2, '0'))
  return amount > 0n && amount <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(amount) : null
}

export function parsePortion(value) {
  const text = String(value).trim().replace(',', '.')
  if (!text) {
    return fraction(0n)
  }

  const ratio = /^(\d+)\s*\/\s*(\d+)$/.exec(text)
  const decimal = /^(\d+)(?:\.(\d{0,6}))?$/.exec(text)
  if (!ratio && !decimal) {
    return null
  }

  const numerator = ratio ? BigInt(ratio[1]) : BigInt(`${decimal[1]}${decimal[2] || ''}`)
  const denominator = ratio ? BigInt(ratio[2]) : 10n ** BigInt((decimal[2] || '').length)
  if (denominator === 0n) {
    return null
  }

  const result = fraction(numerator, denominator)
  const limit = BigInt(Number.MAX_SAFE_INTEGER)
  return result.numerator <= limit && result.denominator <= limit ? result : null
}

export function getAssignmentsTotal(assignments) {
  return assignments.reduce(
    (total, assignment) => addPortions(total, fraction(BigInt(assignment.unit_count), BigInt(assignment.denominator || 1))),
    fraction(0n)
  )
}

export function getUnassignedPortion(quantity, assignments) {
  const assigned = getAssignmentsTotal(assignments)
  return fraction(BigInt(quantity) * assigned.denominator - assigned.numerator, assigned.denominator)
}

export function getUnassignedDraft(transaction) {
  if (!transaction) {
    return ''
  }

  const allocated = (transaction.assignments || []).filter((assignment) => assignment.debtors?.length)
  return formatPortion(getUnassignedPortion(transaction.quantity, allocated))
}

export function getUnassignedForPortions(quantityBaseline, portions) {
  const assignments = assignmentsFromPortions(portions)
  if (!assignments) {
    return null
  }

  const allocated = getAssignmentsTotal(assignments)
  const result = addPortions(quantityBaseline, { numerator: -allocated.numerator, denominator: allocated.denominator })
  return result.numerator < 0n ? '0' : formatPortion(result)
}

export function getPersonPortions(assignments) {
  const portions = {}
  for (const assignment of assignments) {
    const debtors = assignment.debtors || []
    if (debtors.length === 0) {
      continue
    }

    const share = fraction(BigInt(assignment.unit_count), BigInt(assignment.denominator || 1) * BigInt(debtors.length))
    for (const personId of debtors) {
      portions[personId] = addPortions(portions[personId] || fraction(0n), share)
    }
  }

  return Object.fromEntries(Object.entries(portions).map(([personId, portion]) => [personId, formatPortion(portion)]))
}

export function assignmentsFromPortions(portions) {
  const assignments = []
  for (const [personId, value] of Object.entries(portions)) {
    const portion = parsePortion(value)
    if (!portion) {
      return null
    }

    if (portion.numerator > 0n) {
      assignments.push({
        unit_count: Number(portion.numerator),
        denominator: Number(portion.denominator),
        debtors: [personId],
      })
    }
  }

  return assignments
}

export function deriveItemDistribution({ portions, unassigned, preserved = null, original = null }) {
  const allocated = preserved
    ? (preserved.assignments || []).filter((assignment) => assignment.debtors?.length)
    : assignmentsFromPortions(portions)
  const remaining = parsePortion(unassigned)
  if (!allocated || !remaining) {
    return { assignments: null, quantity: null, total: null, remaining }
  }

  const total = addPortions(getAssignmentsTotal(allocated), remaining)
  const quantity = parseQuantity(formatPortion(total))
  if (original && quantity === original.quantity) {
    const currentPortions = getPersonPortions(allocated)
    const originalPortions = getPersonPortions(original.assignments || [])
    const samePeople = Object.keys(currentPortions).length === Object.keys(originalPortions).length
      && Object.entries(currentPortions).every(([personId, value]) => originalPortions[personId] === value)
    if (samePeople && formatPortion(remaining) === getUnassignedDraft(original)) {
      return { assignments: original.assignments || [], quantity, total, remaining }
    }
  }

  if (preserved && quantity === preserved.quantity) {
    return { assignments: preserved.assignments || [], quantity, total, remaining }
  }

  const assignments = [...allocated]
  if (remaining.numerator > 0n) {
    assignments.push({ unit_count: Number(remaining.numerator), denominator: Number(remaining.denominator), debtors: [] })
  }

  return { assignments, quantity, total, remaining }
}

export function getPersonAmounts(assignments, unitPriceMinor, creditor) {
  const amounts = {}
  for (const assignment of assignments) {
    const debtors = [...(assignment.debtors || [])].sort((left, right) => Number(left === creditor) - Number(right === creditor))
    if (debtors.length === 0) {
      continue
    }

    const denominator = BigInt(assignment.denominator || 1)
    const total = (BigInt(unitPriceMinor) * BigInt(assignment.unit_count) + denominator / 2n) / denominator
    const count = BigInt(debtors.length)
    for (const [index, personId] of debtors.entries()) {
      const share = total / count + (BigInt(index) < total % count ? 1n : 0n)
      amounts[personId] = (amounts[personId] || 0) + Number(share)
    }
  }

  return amounts
}

export function formatItemMoney(minor, currency) {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: currency || 'BYN',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(minor / 100)
}

export function getDistributionCardCount(quantity, assignments) {
  let count = assignments.reduce(
    (total, assignment) => total + BigInt(assignment.unit_count) * BigInt(assignment.debtors?.length || 1),
    0n
  )
  const remaining = getUnassignedPortion(quantity, assignments)
  if (remaining.numerator > 0n) {
    const remainder = fraction(remaining.numerator % remaining.denominator, remaining.denominator)
    count += remaining.numerator / remaining.denominator + remainder.numerator
  }

  return count
}

export function getDistributionSizeError(quantity, assignments) {
  if (getDistributionCardCount(quantity, assignments) <= BigInt(MAX_DISTRIBUTION_CARDS)) {
    return null
  }

  return `Слишком много частей позиции — максимум ${MAX_DISTRIBUTION_CARDS}. Укажи простую дробь, например 1/3, или выбери «Поровну».`
}

export function getBillDistributionSizeError(transactions) {
  for (const transaction of transactions) {
    const error = getDistributionSizeError(transaction.quantity, transaction.assignments || [])
    if (error) {
      return `«${transaction.item_name || 'Позиция'}»: ${error}`
    }
  }

  return null
}

export function buildDistributionCards(transactions, nextId) {
  const error = getBillDistributionSizeError(transactions)
  if (error) {
    throw new RangeError(error)
  }

  const cards = []
  for (const transaction of transactions) {
    for (const assignment of transaction.assignments || []) {
      const debtors = assignment.debtors?.length ? assignment.debtors : [null]
      const denominator = (assignment.denominator || 1) * debtors.length
      for (const personId of debtors) {
        for (let index = 0; index < assignment.unit_count; index += 1) {
          cards.push({ id: nextId(), txId: transaction.id, den: denominator, owner: personId })
        }
      }
    }

    const remaining = getUnassignedPortion(transaction.quantity, transaction.assignments || [])
    if (remaining.numerator <= 0n) {
      continue
    }

    const whole = remaining.numerator / remaining.denominator
    const remainder = fraction(remaining.numerator % remaining.denominator, remaining.denominator)
    for (let index = 0n; index < whole; index += 1n) {
      cards.push({ id: nextId(), txId: transaction.id, den: 1, owner: null })
    }

    for (let index = 0n; index < remainder.numerator; index += 1n) {
      cards.push({ id: nextId(), txId: transaction.id, den: Number(remainder.denominator), owner: null })
    }
  }

  return cards
}

export function getCardDistributionKey(cards) {
  const groups = new Map()
  for (const card of cards) {
    const key = JSON.stringify([card.txId, card.owner, card.den])
    groups.set(key, (groups.get(key) || 0) + 1)
  }

  return JSON.stringify([...groups].sort(([left], [right]) => left.localeCompare(right)))
}
