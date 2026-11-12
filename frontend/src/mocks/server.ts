import { setupServer } from 'msw/node'
import { handlers } from './handlers'
import { objectsHandlers } from './objectsHandlers'
import { setupHandlers } from './setupHandlers'

// The object extras go first: `/objects/:type/_bulk` must win over `/objects/:type/:dn`.
export const server = setupServer(...setupHandlers, ...objectsHandlers, ...handlers)
