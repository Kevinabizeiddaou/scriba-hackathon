/**
 * The evaluation screen, as its own chunk. It registers the mock data layer, because the
 * harness self-test runs its scripted reference agent on it. Nothing here touches live data.
 */
import '../harness/mock/runtime'
import { EvaluationPage } from '../pages/EvaluationPage'

export default EvaluationPage
