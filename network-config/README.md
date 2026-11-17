# Hyperledger Fabric Network Configuration

This directory contains the network configuration files used as the basis for the Hyperledger Fabric component of the Solar Billing Audit project.

The configuration is adapted from the Hyperledger Fabric `test-network` sample. It is maintained separately from the application chaincode and Gateway client.

## 1. Network Architecture

The configuration describes a Fabric network with:

- Two peer organizations: Org1 and Org2.
- One ordering organization: OrdererOrg.
- One Raft ordering service consenter in the `ChannelUsingRaft` profile.
- TLS enabled for peer and ordering-node communication.
- Docker Compose configuration for peer and ordering services.
- CouchDB as the peer state database.
- Fabric Certificate Authority configuration files.
- Cryptogen configuration files for organization identities.

The `ChannelUsingRaft` profile defines the application channel with Org1 and Org2.

## 2. Directory Structure

- `test-network/.env.example`
- `test-network/configtx/configtx.yaml`
- `test-network/compose/compose-ca.yaml`
- `test-network/compose/compose-couch.yaml`
- `test-network/compose/compose-test-net.yaml`
- `test-network/compose/docker/docker-compose-test-net.yaml`
- `test-network/compose/docker/peercfg/core.yaml`
- `test-network/cryptogen/crypto-config-orderer.yaml`
- `test-network/cryptogen/crypto-config-org1.yaml`
- `test-network/cryptogen/crypto-config-org2.yaml`

## 3. Configuration Files

- `configtx/configtx.yaml`: Defines the channel and ordering-service configuration.
- `compose/compose-test-net.yaml`: Defines peer and ordering-node services.
- `compose/compose-ca.yaml`: Defines Fabric Certificate Authority services.
- `compose/compose-couch.yaml`: Defines CouchDB services and peer database settings.
- `compose/docker/docker-compose-test-net.yaml`: Contains Docker-specific overrides.
- `compose/docker/peercfg/core.yaml`: Contains peer configuration settings.
- `cryptogen/`: Contains cryptographic identity-generation templates.

## 4. Credentials and Environment Variables

The `.env.example` file documents the environment variables required for local CA and CouchDB credentials.

For local development, copy the example file:

    cp .env.example .env

Replace the placeholder passwords in `.env` before starting services.

Never commit `.env`, private keys, wallets, generated MSP directories, or CA private material to Git.

## 5. Generated Files and Runtime Dependencies

This directory contains configuration templates, not a complete standalone Fabric network distribution.

Network startup also depends on Hyperledger Fabric sample scripts, Fabric binaries, Docker, generated cryptographic identities, channel artifacts, and other supporting files.

Generated files such as `organizations/` and channel artifacts should remain local and must not be committed.

## 6. Important Configuration Review Notes

- The `ChannelUsingRaft` profile currently defines one active Raft consenter.
- The orderer cryptogen configuration contains four orderer host specifications. These settings are not the same as active ordering-service membership. Review them before generating a new network.
- Docker image tags using `latest` may affect reproducibility. For repeatable experiments, use explicitly versioned image tags and document the versions.
- Review all paths and environment variables before using these templates outside the original project environment.

## 7. Project Scope

These configuration files support the Hyperledger Fabric implementation of the Solar Billing Audit project. They provide the configuration basis for the permissioned blockchain network used to record and verify solar billing audit data.

## 8. Source and License

The configuration is adapted from the Hyperledger Fabric `test-network` sample. Retain the original license and copyright notices in the source files.

Hyperledger Fabric sample materials are distributed under the Apache License 2.0.
