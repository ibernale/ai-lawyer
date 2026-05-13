import nextConfig from "eslint-config-next/core-web-vitals";

const config = [
  ...nextConfig,
  {
    rules: {
      // Disabled: false-positive on async data-loading pattern (void load() in useEffect
      // where setState is only called after await). TODO: migrate to useReducer or React Query.
      "react-hooks/set-state-in-effect": "off",
      // Disabled: flags Date.now() in module-level helpers. React purity rules do not apply
      // to pure utility functions defined outside components; re-enable when React Compiler lands.
      "react-hooks/purity": "off",
    },
  },
];

export default config;
