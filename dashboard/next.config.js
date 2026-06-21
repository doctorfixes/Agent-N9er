/** @type {import('next').NextConfig} */
module.exports = {
  output: process.env.NETLIFY ? undefined : "standalone",
  serverExternalPackages: [],
};
