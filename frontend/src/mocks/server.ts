import { setupServer } from 'msw/node'
import { handlers } from './handlers'
import { objectsHandlers } from './objectsHandlers'

// The object extras go first: `/objects/:type/_bulk` must win over `/objects/:type/:dn`.
export const server = setupServer(...objectsHandlers, ...handlers)
