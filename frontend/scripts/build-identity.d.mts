export interface BuildIdentityInput {
  base: string;
  sha: string;
  builtAt: string;
  repoUrl?: string;
}

export interface BuildIdentity {
  version: string;
  commitShort: string;
  builtAt: string;
  repoUrl: string;
}

export function composeBuildIdentity(input: BuildIdentityInput): BuildIdentity;
export function validateBuildIdentity(identity: BuildIdentity): BuildIdentity;
