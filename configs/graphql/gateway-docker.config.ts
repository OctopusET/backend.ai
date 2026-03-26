import { defineConfig, type GatewayPlugin } from '@graphql-hive/gateway';

const useConnectionParamsToHeadersPlugin = (): GatewayPlugin => {
  return {
    onSubgraphExecute({ executionRequest, executor, setExecutor }) {
      const originalExecutor = executor;
      const wrappedExecutor = async (execRequest: any) => {
        let reqHeaders = execRequest.context.headers || {};
        let new_headers = {};
        if (reqHeaders["x-backendai-token"]) {
          new_headers = {
            "x-backendai-token": reqHeaders["x-backendai-token"]
          };
        }
        const modifiedRequest = {
          ...execRequest,
          extensions: { headers: new_headers },
        };
        return originalExecutor(modifiedRequest);
      };
      setExecutor(wrappedExecutor);
    },
  };
};

export const gatewayConfig = defineConfig({
  plugins: (ctx) => [
    useConnectionParamsToHeadersPlugin(),
  ],
  propagateHeaders: {
    fromClientToSubgraphs({ context }) {
      let headers = context.headers || {};
      delete headers['content-length'];
      return headers;
    },
  },
  disableIntrospection: {
    disableIf: () => true
  },
  maskedErrors: false,
  logging: false,
  supergraph: '/gateway/supergraph.graphql',
  graphqlEndpoint: '/admin/gql',
  skipValidation: true,
  transportEntries: {
    GRAPHENE: {
      location: 'http://127.0.0.1:8081/admin/gql',
    },
    STRAWBERRY: {
      location: 'http://127.0.0.1:8081/admin/gql/strawberry',
    },
    '*.http': {
      options: {
        subscriptions: {
          kind: 'ws',
          headers: [
            ['x-backendai-token', '{context.headers.x-backendai-token}']
          ]
        },
      }
    },
  },
});
